import hashlib
import json
import logging

from django.db.models import Q
from django.http import JsonResponse
from django.views.generic import View
from django_scopes import scope

from pretix.base.models import Seat, SeatCategoryMapping
from pretix.presale.views import EventViewMixin, get_cart

logger = logging.getLogger(__name__)


class SeatmapDataAPIView(EventViewMixin, View):
    def get(self, request, *args, **kwargs):
        event = self.request.event
        seats_data = []
        categories = {}
        cart = get_cart(self.request)
        seating_plan_data = {}

        if event.settings.seating_choice and event.seating_plan:
            # Pre-populate all categories from the seating plan layout.
            for cat in event.seating_plan.get_categories():
                cat_id = str(cat.name).encode('utf-8')
                color_hash = hashlib.sha1(cat_id).hexdigest()
                category_color = f"#{color_hash[:6]}"
                categories[cat.name] = {
                    'name': cat.name,
                    'color': category_color,
                }

            with scope(organizer=event.organizer):
                # Prefetch all available products for availability checks
                products_by_id = {p.id: p for p in event.items.all()}

                qs = event.seats.select_related('product', 'product__category')
                subevent = getattr(self.request, "subevent", None)
                seats = Seat.annotated(qs, event.id, subevent)
                cart_seats = {p.seat.seat_guid for p in cart if p.seat}

                # Load mappings from layout categories to products.
                category_mappings = {}
                q_mappings = SeatCategoryMapping.objects.filter(event=event).select_related('product')
                if subevent:
                    # We need to get the specific mapping for the subevent, but fall back to the general one.
                    # .order_by('subevent_id') on postgres places NULLs last, so the general mapping would overwrite
                    # the specific one. .reverse() fixes this by processing NULLs (general mappings) first.
                    q_mappings = q_mappings.filter(Q(subevent=subevent) | Q(subevent__isnull=True)).order_by('subevent_id').reverse()
                else:
                    q_mappings = q_mappings.filter(subevent__isnull=True)

                for mapping in q_mappings:
                    category_mappings[mapping.layout_category] = {
                        'product_id': mapping.product.id,
                    }

                # Parse the layout to create a map from seat GUID to its layout category name.
                seating_plan_data = json.loads(event.seating_plan.layout or '{}')
                seat_guid_to_layout_category = {}

                def find_seat_categories(layout_data):
                    """Search for seat categories in zones -> rows -> seats structure."""
                    if 'zones' in layout_data:
                        for zone in layout_data.get('zones', []):
                            if 'rows' in zone:
                                for row in zone.get('rows', []):
                                    row_category = row.get('category')
                                    if 'seats' in row:
                                        for seat in row.get('seats', []):
                                            seat_guid = seat.get('seat_guid')
                                            if not seat_guid:
                                                continue
                                            seat_category = seat.get('category')
                                            if seat_category:
                                                seat_guid_to_layout_category[seat_guid] = seat_category
                                            elif row_category:
                                                seat_guid_to_layout_category[seat_guid] = row_category
                    elif 'seats' in layout_data:
                        for seat in layout_data.get('seats', []):
                            seat_guid = seat.get('seat_guid')
                            seat_category = seat.get('category')
                            if seat_guid and seat_category:
                                seat_guid_to_layout_category[seat_guid] = seat_category

                find_seat_categories(seating_plan_data)

                for seat in seats:
                    layout_category_name = seat_guid_to_layout_category.get(seat.seat_guid)

                    product_id = None
                    if seat.product:
                        product_id = seat.product.id
                    elif layout_category_name and layout_category_name in category_mappings:
                        product_id = category_mappings[layout_category_name]['product_id']

                    product = products_by_id.get(product_id)

                    # Check for general product availability
                    is_available = product and product.is_available()

                    # If a subevent is selected, check for subevent-specific availability overrides
                    if is_available and subevent:
                        if product.pk in subevent.item_overrides:
                            if not subevent.item_overrides[product.pk].is_available():
                                is_available = False

                    status = 'available'
                    if not is_available:
                        status = 'unavailable'
                    elif seat.seat_guid in cart_seats:
                        status = 'selected'
                    elif seat.has_order or (seat.has_cart and seat.seat_guid not in cart_seats) or seat.has_voucher:
                        status = 'unavailable'

                    category_color = None
                    if layout_category_name and layout_category_name in categories:
                        category_color = categories[layout_category_name]['color']
                    else:
                        category_color = "#CCCCCC"

                    seats_data.append({
                        'guid': seat.seat_guid,
                        'x': seat.x,
                        'y': seat.y,
                        'r': 10,
                        'name': seat.name,
                        'category': layout_category_name or '',
                        'category_color': category_color,
                        'product': product_id,
                        'status': status,
                    })

        response_data = {
            'seats': seats_data,
            'seating_plan': seating_plan_data,
            'seat_categories': list(categories.values())
        }

        return JsonResponse(response_data)
