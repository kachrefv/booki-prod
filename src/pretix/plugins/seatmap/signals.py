import hashlib
import json

from django.contrib import messages
from django.contrib.staticfiles import finders
from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _
from django_scopes import scope

from pretix.base.models import Seat
from pretix.control.signals import nav_event, nav_organizer
from pretix.helpers.http import redirect_to_url
from pretix.presale.checkoutflow import TemplateFlowStep
from pretix.presale.signals import checkout_flow_steps
from pretix.presale.views import get_cart

try:
    seat_icon = open(finders.find("seatmap/icons/seat.svg", all=False)).read()
except (IOError, TypeError):
    seat_icon = ''


@receiver(nav_event, dispatch_uid="manualsets_nav")
def control_nav_manualseats(sender, request=None, **kwargs):
    url = resolve(request.path_info)
    if not request.user.has_event_permission(
        request.organizer, request.event, "can_change_event_settings", request=request
    ):
        return []
    return [
        {
            "label": _("Seat Map"),
            "url": reverse(
                "plugins:seatmap:event.index",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.event.organizer.slug,
                },
            ),
            "active": (
                "plugins:seatmap:event.index" in url.url_name
                or "plugins:seatmap:event.mapping" in url.url_name
                or "plugins:seatmap:event.assign" in url.url_name
            ),
            "icon": seat_icon,
            "children": [
                {
                    "label": _("Category Mapping"),
                    "url": reverse(
                        "plugins:seatmap:event.mapping",
                        kwargs={
                            "event": request.event.slug,
                            "organizer": request.event.organizer.slug,
                        },
                    ),
                    "active": "plugins:seatmap:event.mapping" in url.url_name,
                },
                {
                    "label": _("Seat Assignment"),
                    "url": reverse(
                        "plugins:seatmap:event.assign",
                        kwargs={
                            "event": request.event.slug,
                            "organizer": request.event.organizer.slug,
                        },
                    ),
                    "active": "plugins:seatmap:event.assign" in url.url_name,
                },
            ],
        },
    ]


@receiver(nav_organizer, dispatch_uid="manualseats_orga_nav")
def control_nav_orga_manualseats(sender, request=None, **kwargs):
    url = resolve(request.path_info)
    if not request.user.has_organizer_permission(
        request.organizer, "can_change_organizer_settings", request=request
    ):
        return []
    if not request.organizer.events.filter(plugins__icontains="seatmap"):
        return []
    return [
        {
            "label": _("Seating Plans"),
            "url": reverse(
                "plugins:seatmap:organizer.index",
                kwargs={
                    "organizer": request.organizer.slug,
                },
            ),
            "active": (url.namespace == "plugins:seatmap" and 'organizer' in url.url_name),
            "icon": seat_icon,
        },
    ]


class SeatSelectionStep(TemplateFlowStep):
    identifier = "seats"
    label = _("Choose your seats")
    priority = 55
    template_name = 'seatmap/presale/checkout_seats.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event = self.request.event
        cart = get_cart(self.request)

        seats_data = []
        categories = {}
        if event.settings.seating_choice and event.seating_plan:
            with scope(organizer=event.organizer):
                qs = event.seats.select_related('product', 'product__category')
                subevent = getattr(self.request, "subevent", None)
                seats = Seat.annotated(qs, event.id, subevent)
                cart_seats = {p.seat.seat_guid for p in cart if p.seat}

                for seat in seats:
                    status = 'available'
                    if seat.has_order or (seat.has_cart and seat.seat_guid not in cart_seats) or seat.has_voucher:
                        status = 'unavailable'

                    category_color = None
                    category_name = ''
                    if seat.product and seat.product.category:
                        category_name = seat.product.category.name
                        if seat.product.category.id not in categories:
                            cat_id = str(seat.product.category.id).encode('utf-8')
                            color_hash = hashlib.sha1(cat_id).hexdigest()
                            category_color = f"#{color_hash[:6]}"
                            categories[seat.product.category.id] = {
                                'name': category_name,
                                'color': category_color,
                            }
                        else:
                            category_color = categories[seat.product.category.id]['color']

                    seats_data.append({
                        'guid': seat.seat_guid,
                        'x': seat.x,
                        'y': seat.y,
                        'r': 10,
                        'name': seat.name,
                        'category': category_name,
                        'category_color': category_color,
                        'product': seat.product.id if seat.product else None,
                        'status': status
                    })

        ctx['seats_json'] = json.dumps(seats_data)
        ctx['seat_categories'] = json.dumps(list(categories.values()))
        ctx['seating_plan_json'] = (event.seating_plan.layout or '{}') if event.seating_plan else '{}'
        ctx['select_url'] = reverse('plugins:seatmap:select', kwargs={
            'organizer': event.organizer.slug,
            'event': event.slug,
        })

        positions_with_seats = [
            {
                'id': p.pk,
                'item_name': str(p.item),
                'variation_name': str(p.variation) if p.variation else '',
                'seat': p.seat.seat_guid if p.seat else None
            }
            for p in cart if p.item.admission
        ]
        ctx['positions_need_seats'] = json.dumps(positions_with_seats)
        return ctx

    def get(self, request, *args, **kwargs):
        self.request = request
        return self.render()

    def post(self, request, *args, **kwargs):
        self.request = request
        if self.is_completed(request):
            return redirect_to_url(self.get_next_url(request))
        messages.error(request, _("You need to select seats for all your tickets."))
        return redirect_to_url(self.get_step_url(request))

    def is_applicable(self, request):
        cart = get_cart(request)
        return (
            cart is not None
            and request.event.settings.seating_choice
            and request.event.seating_plan
            and any(p.item.admission and not p.seat for p in cart)
        )

    def is_completed(self, request, warn=False):
        cart = get_cart(request)
        completed = cart is None or not any(p.item.admission and not p.seat for p in cart)
        if not completed and warn:
            messages.warning(request, _('Please select a seat for every ticket.'))
        return completed


@receiver(checkout_flow_steps, dispatch_uid="manualseats_checkout_step")
def manualseats_checkout_step(sender, **kwargs):
    return SeatSelectionStep
