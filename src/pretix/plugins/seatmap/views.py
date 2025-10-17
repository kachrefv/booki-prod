import json
import logging
import typing
from typing import Any, Dict

from django import forms
from django.contrib import messages
from django.db import models, transaction
from django.db.models import Count, Q
from django.forms.forms import BaseForm
from django.forms.models import BaseModelForm
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    CreateView, FormView, ListView, TemplateView, UpdateView, View,
)
from django_scopes import scope

from pretix.base.forms import I18nModelForm
from pretix.base.models import (
    CartPosition,
    Event,
    Item,
    Order,
    OrderPosition,
    Organizer,
    Quota,
    Seat,
    SeatCategoryMapping,
    SeatingPlan,
)
from pretix.base.services.seating import generate_seats
from pretix.control.permissions import (
    EventPermissionRequiredMixin,
    OrganizerPermissionRequiredMixin,
)
from pretix.helpers.compat import CompatDeleteView
from pretix.helpers.models import modelcopy
from pretix.multidomain.urlreverse import eventreverse
from pretix.presale.views import EventViewMixin, get_cart
from pretix.presale.views.cart import get_or_create_cart_id

logger = logging.getLogger(__name__)


class CheckoutSeatSelectionView(EventViewMixin, View):
    template_name = 'seatmap/presale/checkout_seats.html'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.get_context_data())

    def get_context_data(self, **kwargs):
        ctx = {}
        event = self.request.event
        cart = get_cart(self.request)

        seats_data = []
        categories = {}
        layout_data = {}

        if event.settings.seating_choice and event.seating_plan and event.seating_plan.layout:
            try:
                # [FIX] Robustly parse seating plan layout to prevent JS errors
                layout_data = json.loads(event.seating_plan.layout)
                if isinstance(layout_data, str):
                    # Handle cases where the layout might be double-encoded JSON
                    layout_data = json.loads(layout_data)
                if not isinstance(layout_data, dict):
                    raise TypeError("Layout is not a dictionary")
            except (json.JSONDecodeError, TypeError):
                logger.exception(f"Could not parse seating plan layout for event {event.id}.")
                layout_data = {}

            if layout_data:
                with scope(organizer=event.organizer):
                    subevent = getattr(self.request, "subevent", None)
                    seats = Seat.annotated(event.seats.all(), event.id, subevent)
                    cart_seats = {p.seat.seat_guid for p in cart if p.seat}

                    product_mappings = {
                        m.layout_category: m.product
                        for m in SeatCategoryMapping.objects.filter(event=event).select_related('product', 'product__category')
                    }

                    # Build helper maps from the parsed layout data for efficient lookups
                    guid_to_category_name = {
                        seat_plan.get('seat_guid'): seat_plan.get('category')
                        for zone in layout_data.get('zones', [])
                        for row in zone.get('rows', [])
                        for seat_plan in row.get('seats', [])
                    }
                    category_name_to_color = {
                        c.get('name'): c.get('color')
                        for c in layout_data.get('categories', [])
                    }

                    for seat in seats:
                        category_name = guid_to_category_name.get(seat.seat_guid)
                        product = product_mappings.get(category_name)

                        is_unavailable = (
                            seat.has_order or
                            (seat.has_cart and seat.seat_guid not in cart_seats) or
                            seat.has_voucher or
                            seat.blocked or
                            not product  # A seat is unavailable if no product is mapped to its category
                        )
                        status = 'unavailable' if is_unavailable else 'available'

                        category_color = category_name_to_color.get(category_name)
                        display_category_name = category_name

                        if product and product.category:
                            display_category_name = product.category.name
                            if product.category.id not in categories:
                                categories[product.category.id] = {
                                    'name': str(display_category_name),
                                    'color': category_color,
                                }
                        elif category_name:
                            # Fallback for legend if no product/product.category is available
                            if category_name not in [c['name'] for c in categories.values()]:
                                categories[category_name] = {
                                    'name': str(category_name),
                                    'color': category_color,
                                }

                        seats_data.append({
                            'guid': seat.seat_guid,
                            'x': seat.x,
                            'y': seat.y,
                            'r': 10,  # Assuming radius is constant
                            'name': str(seat.name),
                            'category': str(display_category_name) if display_category_name else None,
                            'category_color': category_color,
                            'product': product.id if product else None,
                            'status': status
                        })

        # [FIX] Always pass a valid, re-serialized JSON object string to the template
        ctx['seats_json'] = json.dumps(seats_data)
        ctx['seat_categories'] = json.dumps(list(categories.values()))
        ctx['seating_plan_json'] = json.dumps(layout_data)
        ctx['select_url'] = reverse('plugins:seatmap:checkout.seats', kwargs={
            'organizer': event.organizer.slug,
            'event': event.slug,
        })

        positions_with_seats = [
            {
                'id': p.pk,
                'item_name': str(p.item),
                'variation_name': str(p.variation) if p.variation else '',
                'seat': p.seat.seat_guid if p.seat else None,
                'product': p.item.pk
            }
            for p in cart if p.item.admission
        ]
        ctx['positions_need_seats'] = json.dumps(positions_with_seats)
        ctx['event'] = event
        return ctx

    def is_seat_taken(self, seat: Seat, exclude_cart_position_id: int = None):
        if OrderPosition.objects.filter(
            seat=seat,
            order__status__in=[Order.STATUS_PENDING, Order.STATUS_PAID]
        ).exists():
            return True

        cpq = CartPosition.objects.filter(seat=seat, expires__gte=now())
        if exclude_cart_position_id:
            cpq = cpq.exclude(pk=exclude_cart_position_id)
        if cpq.exists():
            return True

        if seat.vouchers.filter(
            Q(Q(valid_until__isnull=True) | Q(valid_until__gte=now())) &
            Q(redeemed__lt=models.F('max_usages'))
        ).exists():
            return True

        return False

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        logger.debug("CheckoutSeatSelectionView POST request received.")
        try:
            data = json.loads(request.body)
            seat_assignments = data.get('seat_assignments', {})  # {position_id: seat_guid}
            cart_id = get_or_create_cart_id(request)
            event = request.event

            positions = list(CartPosition.objects.filter(
                cart_id=cart_id, event=event, item__admission=True
            ))
            position_map = {str(p.pk): p for p in positions}

            for pos_id in seat_assignments.keys():
                if pos_id not in position_map:
                    msg = _('Your shopping cart has expired or has been changed in the meantime. Please go back to the cart, check your selection and try again.')
                    logger.warning(f"Position ID {pos_id} not in cart. Aborting.")
                    return JsonResponse({'status': 'error', 'message': str(msg)}, status=400)

            if len(seat_assignments.values()) != len(set(seat_assignments.values())):
                logger.warning("Duplicate seats assigned to multiple tickets.")
                return JsonResponse({'status': 'error', 'message': str(_('The same seat cannot be assigned to multiple tickets.'))}, status=400)

            seats_to_assign = {}
            for pos_id, seat_guid in seat_assignments.items():
                try:
                    seat = Seat.objects.get(seat_guid=seat_guid, event=event)
                    if self.is_seat_taken(seat, exclude_cart_position_id=int(pos_id)):
                        logger.warning(f"Seat {seat.name} ({seat_guid}) is no longer available.")
                        return JsonResponse({'status': 'error', 'message': str(_('Seat {seat_name} is no longer available.').format(seat_name=seat.name))}, status=400)
                    seats_to_assign[pos_id] = seat
                except Seat.DoesNotExist:
                    logger.error(f"Seat with GUID {seat_guid} not found.")
                    return JsonResponse({'status': 'error', 'message': str(_('Invalid seat selected.'))}, status=404)

            logger.debug("Clearing existing seat assignments for these positions.")
            CartPosition.objects.filter(pk__in=position_map.keys()).update(seat=None)

            for pos_id, seat in seats_to_assign.items():
                pos = position_map[pos_id]
                pos.seat = seat
                pos.save()

            kwargs = {}
            if 'cart_namespace' in self.request.resolver_match.kwargs:
                kwargs['cart_namespace'] = self.request.resolver_match.kwargs['cart_namespace']

            redirect_url = eventreverse(
                self.request.event,
                'presale:event.checkout.start',
                kwargs=kwargs
            )
            return JsonResponse({'status': 'success', 'redirect': redirect_url})

        except json.JSONDecodeError:
            logger.error("Failed to decode JSON from request body.")
            return JsonResponse({'status': 'error', 'message': str(_('Invalid request.'))}, status=400)
        except Exception as e:
            logger.exception("An unexpected error occurred while saving seats.")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


class SeatSelectionView(EventViewMixin, View):

    def is_seat_taken(self, seat: Seat, exclude_cart_position_id: int = None):
        """Check if a seat is already taken by another order or another cart."""
        # Check if seat is in any paid or pending orders
        if OrderPosition.objects.filter(
            seat=seat,
            order__status__in=[Order.STATUS_PENDING, Order.STATUS_PAID]
        ).exists():
            return True

        # Check if seat is in any other active cart
        cpq = CartPosition.objects.filter(seat=seat, expires__gte=now())
        if exclude_cart_position_id:
            cpq = cpq.exclude(pk=exclude_cart_position_id)
        if cpq.exists():
            return True

        # Check if seat is reserved by any active voucher
        if seat.vouchers.filter(
            Q(Q(valid_until__isnull=True) | Q(valid_until__gte=now())) &
            Q(redeemed__lt=models.F('max_usages'))
        ).exists():
            return True

        return False

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            seat_assignments = data.get('seat_assignments', {})  # {position_id: seat_guid}
            cart_id = get_or_create_cart_id(request)
            event = request.event

            # Get all cart positions for this user that require a seat
            positions = list(CartPosition.objects.filter(
                cart_id=cart_id, event=event, item__admission=True
            ))
            position_map = {str(p.pk): p for p in positions}

            # --- Validation ---
            # 1. Check for invalid position IDs
            for pos_id in seat_assignments.keys():
                if pos_id not in position_map:
                    msg = _('Your shopping cart has expired or has been changed in the meantime. Please go back to the cart, check your selection and try again.')
                    return JsonResponse({'status': 'error', 'message': str(msg)}, status=400)

            # 2. Check for seats being assigned to multiple positions in the same request
            if len(seat_assignments.values()) != len(set(seat_assignments.values())):
                return JsonResponse({'status': 'error', 'message': str(_('The same seat cannot be assigned to multiple tickets.'))}, status=400)

            # 3. Check seat existence and availability
            seats_to_assign = {}
            for pos_id, seat_guid in seat_assignments.items():
                try:
                    seat = Seat.objects.get(seat_guid=seat_guid, event=event)
                    if self.is_seat_taken(seat, exclude_cart_position_id=int(pos_id)):
                        return JsonResponse({'status': 'error', 'message': str(_('Seat {seat_name} is no longer available.').format(seat_name=seat.name))}, status=400)
                    seats_to_assign[pos_id] = seat
                except Seat.DoesNotExist:
                    return JsonResponse({'status': 'error', 'message': str(_('Invalid seat selected.'))}, status=404)

            # --- Update cart positions ---
            # First, clear all existing seat assignments for this user's admission items
            CartPosition.objects.filter(pk__in=position_map.keys()).update(seat=None)

            # Then, assign the new seats
            for pos_id, seat in seats_to_assign.items():
                pos = position_map[pos_id]
                pos.seat = seat
                pos.save()

            return JsonResponse({'status': 'success'})

        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': str(_('Invalid request.'))}, status=400)
        except Exception as e:
            logger.exception("Could not save seats")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


class EventSeatingPlanSetForm(forms.Form):
    seatingplan = forms.ChoiceField(required=False, label=_("Seating Plan"))
    advanced = forms.BooleanField(label=_("Advanced Settings"), required=False)
    users_edit_seatingplan = forms.BooleanField(
        label=_("Customers can choose their own seats"),
        widget=forms.CheckboxInput(attrs={"data-display-dependency": "#id_advanced"}),
        help_text=_(
            "If disabled, you will need to manually assign seats in the backend. "
            "Note that this can mean people will not know their seat after their purchase and it might not be written on their ticket."
        ),
        required=False,
    )

    class Meta:
        fields = ["users_edit_seatingplan", "seatingplan"]


class EventIndex(EventPermissionRequiredMixin, FormView):
    model = SeatingPlan
    template_name = "seatmap/event/index.html"
    permission = "can_change_orders"
    form_class = EventSeatingPlanSetForm

    def get_success_url(self) -> str:
        return reverse(
            "plugins:seatmap:event.index",
            kwargs={
                "organizer": self.get_event().organizer.slug,
                "event": self.get_event().slug,
            },
        )

    def get_seatingplans(self):
        return SeatingPlan.objects.filter(organizer=self.request.organizer)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["seatingplans"] = self.get_seatingplans()

        return ctx

    def get_event(self) -> Event:
        return self.request.event

    def get_initial(self) -> Dict[str, Any]:
        initial = super().get_initial()

        event = self.get_event()
        initial["seatingplan"] = event.seating_plan.id if event.seating_plan else None
        initial["users_edit_seatingplan"] = event.settings.seating_choice

        return initial

    def get_form(self, form_class=None) -> BaseForm:
        form = typing.cast(EventSeatingPlanSetForm, super().get_form(form_class))

        form.fields["seatingplan"].choices = [(None, _("None"))] + [
            (i.id, i.name) for i in self.get_seatingplans()
        ]

        form.fields["seatingplan"].disabled = self.seats_in_use()

        return form

    def seats_in_use(self):
        return OrderPosition.objects.filter(
            order__event=self.get_event(), seat__isnull=False
        ).exists()

    def form_valid(self, form):
        seatingplan_id = form.cleaned_data["seatingplan"]

        event = self.get_event()
        if seatingplan_id:
            event.seating_plan = SeatingPlan.objects.get(id=seatingplan_id)
            event.settings.seating_choice = form.cleaned_data["users_edit_seatingplan"]
        else:
            if event.seating_plan:
                event.seating_plan = None

        event.save()

        if not self.seats_in_use():
            if event.seating_plan:
                generate_seats(event, None, event.seating_plan, dict(), None)
            else:
                SeatCategoryMapping.objects.filter(event=event).delete()
                Seat.objects.filter(event=event).delete()

        messages.success(self.request, _("Your changes have been saved."))

        return super().form_valid(form)


class EventMappingForm(forms.Form):
    pass


class EventMapping(EventPermissionRequiredMixin, FormView):
    template_name = "seatmap/event/mapping.html"
    permission = "can_change_orders"
    form_class = EventMappingForm

    def get_success_url(self) -> str:
        return reverse(
            "plugins:seatmap:event.mapping",
            kwargs={
                "organizer": self.get_event().organizer.slug,
                "event": self.get_event().slug,
            },
        )

    def get_seatingplans(self):
        return SeatingPlan.objects.filter(organizer=self.request.organizer)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["seatingplan"] = self.get_seating_plan()
        if self.get_seating_plan():
            ctx["seatingcats"] = [
                c.name for c in self.get_seating_plan().get_categories()
            ]
        ctx["items"] = self.get_event().items.all()

        return ctx

    def get_event(self) -> Event:
        return self.request.event

    def get_seating_plan(self) -> Event:
        return self.get_event().seating_plan

    def get_initial(self) -> Dict[str, Any]:
        initial = super().get_initial()

        event = self.get_event()

        if self.get_seating_plan():
            for cat in self.get_seating_plan().get_categories():
                mapping = SeatCategoryMapping.objects.filter(
                    event=event, layout_category=cat.name
                ).first()
                if mapping:
                    initial[f"cat-{cat.name}"] = mapping.product.id

        return initial

    def get_form(self, form_class=None) -> BaseForm:
        form = typing.cast(EventSeatingPlanSetForm, super().get_form(form_class))

        if self.get_seating_plan():
            for cat in self.get_seating_plan().get_categories():
                form.fields[f"cat-{cat.name}"] = forms.ChoiceField(
                    label=cat.name,
                    choices=[(i.id, i.name) for i in self.get_event().items.all()]
                    + [(None, _("None"))],
                    required=False,
                )

        return form

    def form_valid(self, form: BaseForm) -> HttpResponse:
        event = self.get_event()
        SeatCategoryMapping.objects.filter(event=event).delete()

        if self.get_seating_plan():
            for cat in self.get_seating_plan().get_categories():
                if form.cleaned_data[f"cat-{cat.name}"]:
                    product = Item.objects.filter(
                        id=form.cleaned_data[f"cat-{cat.name}"]
                    ).first()
                    queryset = SeatCategoryMapping.objects.create(
                        event=event, layout_category=cat.name, product=product
                    )
                    queryset.save()

        messages.success(self.request, _("Your changes have been saved."))

        return super().form_valid(form)


class EventAssignForm(forms.Form):
    data = forms.CharField(
        widget=forms.Textarea(),
        label=_("Raw Data"),
        help_text=_("Header should equal")
        + ": <code>seat_guid,orderposition_secret</code>",
        required=False,
    )

    pass


class EventAssign(EventPermissionRequiredMixin, FormView):
    template_name = "seatmap/event/assign.html"
    permission = "can_change_orders"
    form_class = EventAssignForm

    def get_success_url(self) -> str:
        return reverse(
            "plugins:seatmap:event.assign",
            kwargs={
                "organizer": self.get_event().organizer.slug,
                "event": self.get_event().slug,
            },
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["seatingplan"] = self.get_seating_plan()
        if self.get_seating_plan():
            ctx["seatingcats"] = [
                c.name for c in self.get_seating_plan().get_categories()
            ]
        ctx["items"] = self.get_event().items.all()
        ctx["seats"] = Seat.objects.filter(event=self.get_event())

        return ctx

    def get_event(self) -> Event:
        return self.request.event

    def get_seating_plan(self) -> Event:
        return self.get_event().seating_plan

    def get_initial(self) -> Dict[str, Any]:
        initial = super().get_initial()

        orderpositions_with_seats = OrderPosition.objects.filter(
            order__event=self.get_event(), seat__isnull=False
        )
        if orderpositions_with_seats:
            initial["data"] = "seat_guid,orderposition_secret\n" + "\n".join(
                [
                    pos.seat.seat_guid + "," + pos.secret
                    for pos in orderpositions_with_seats.select_related("seat")
                ]
            )

        return initial

    def form_valid(self, form: BaseForm) -> HttpResponse:
        event = self.get_event()

        if not event.seating_plan:
            messages.error(self.request, _("No seating plan"))
            return super().form_invalid(form)

        data = typing.cast(str, form.cleaned_data["data"])
        lines = data.split("\n")
        lines = [line.strip() for line in lines]

        if len(lines) <= 1:
            OrderPosition.objects.filter(order__event=event).update(seat=None)
            messages.success(self.request, _("Removed all seat assignments."))
            return super().form_valid(form)

        if not (lines[0].startswith("seat_guid,orderposition_secret")):
            messages.error(
                self.request,
                _(
                    "The CSV input format is invalid. Please check if you have included the headers."
                ),
            )
            return super().form_invalid(form)

        for line in lines[1:]:
            (seat_guid, orderposition_secret) = [
                line.strip() for line in line.split(",")
            ]
            order = OrderPosition.objects.filter(secret=orderposition_secret).first()
            seat = Seat.objects.filter(seat_guid=seat_guid).first()
            if not order:
                messages.error(
                    self.request, _(f"Unable to match order ({orderposition_secret}).")
                )
                return super().form_invalid(form)
            if not seat:
                messages.error(self.request, _(f"Unable to match seat ({seat_guid})."))
                return super().form_invalid(form)

            order.seat = seat
            order.save()

        messages.success(self.request, _("Your changes have been saved."))

        return super().form_valid(form)


class OrganizerSeatingPlanList(OrganizerPermissionRequiredMixin, ListView):
    model = SeatingPlan
    context_object_name = "seatingplans"
    paginate_by = 20
    template_name = "seatmap/organizer/index.html"
    permission = "can_change_organizer_settings"

    def get_queryset(self):
        return (
            SeatingPlan.objects.filter(organizer=self.request.organizer)
            .order_by("id")
            .annotate(eventcount=Count("events"), subeventcount=Count("subevents"))
        )


class SeatingPlanForm(I18nModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = SeatingPlan
        fields = ("name", "layout")


class SeatingPlanDetailMixin:
    def get_object(self, queryset=None) -> SeatingPlan:
        try:
            return SeatingPlan.objects.get(
                organizer=self.request.organizer, id=self.kwargs["seatingplan"]
            )
        except SeatingPlan.DoesNotExist:
            raise Http404(_("The requested seating plan does not exist."))

    def get_success_url(self) -> str:
        return reverse(
            "plugins:seatmap:organizer.index",
            kwargs={"organizer": self.request.organizer.slug},
        )

    def is_in_use(self) -> bool:
        return self.get_object().events.exists() or self.get_object().subevents.exists()


class OrganizerPlanAdd(OrganizerPermissionRequiredMixin, CreateView):
    model = SeatingPlan
    form_class = SeatingPlanForm
    template_name = "seatmap/organizer/form.html"
    permission = "can_change_organizer_settings"

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs)

    def get_success_url(self) -> str:
        return reverse(
            "plugins:seatmap:organizer.index",
            kwargs={
                "organizer": self.request.organizer.slug,
            },
        )

    @transaction.atomic
    def form_valid(self, form):
        form.instance.organizer = self.request.organizer
        messages.success(self.request, _("The new seating plan has been added."))
        ret = super().form_valid(form)
        form.instance.log_action(
            "pretix_seatingplan.seatingplan.added",
            data=dict(form.cleaned_data),
            user=self.request.user,
        )
        self.request.organizer.cache.clear()
        return ret

    def form_invalid(self, form):
        messages.error(self.request, _("Your changes could not be saved."))
        return super().form_invalid(form)

    @cached_property
    def copy_from(self):
        if self.request.GET.get("copy_from") and not getattr(self, "object", None):
            try:
                return SeatingPlan.objects.get(
                    organizer=self.request.organizer,
                    id=self.request.GET.get("copy_from"),
                )
            except SeatingPlan.DoesNotExist:
                raise Http404(
                    _("The requested seating plan does not exist. Can't copy!")
                )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()

        if self.copy_from:
            i = modelcopy(self.copy_from)
            i.id = None
            i.name += " (" + _("Copy") + ")"
            kwargs["instance"] = i
            kwargs.setdefault("initial", {})
        return kwargs


class OrganizerPlanEdit(
    OrganizerPermissionRequiredMixin, SeatingPlanDetailMixin, UpdateView
):
    model = SeatingPlan
    form_class = SeatingPlanForm
    template_name = "seatmap/organizer/form.html"
    permission = "can_change_organizer_settings"

    def get_success_url(self) -> str:
        return reverse(
            "plugins:seatmap:organizer.index",
            kwargs={
                "organizer": self.request.organizer.slug,
            },
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()

        self.get_object()

        ctx["inuse"] = self.is_in_use()

        return ctx

    def get_form(self, form_class: type[BaseModelForm] | None = None) -> BaseModelForm:
        form = super().get_form(form_class)

        form.fields["layout"].disabled = self.is_in_use()

        if self.is_in_use():
            form.fields["layout"].help_text = _(
                "You cannot change this plan any more since it is already used in at least one of your events. Please create a copy instead."
            )

        return form

    @transaction.atomic
    def form_valid(self, form):
        if (
            self.is_in_use()
            and self.request.POST.get("layout")
            and self.get_object().layout != self.request.POST["layout"]
        ):
            messages.error(
                self.request,
                _("Your changes could not be saved. The plan already is in use."),
            )
            return super().form_invalid(form)

        messages.success(self.request, _("Your changes have been saved."))

        if form.has_changed():
            self.object.log_action(
                "pretix_seatingplan.seatingplan.changed",
                data=dict(form.cleaned_data),
                user=self.request.user,
            )

        self.request.organizer.cache.clear()
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, _("Your changes could not be saved."))
        return super().form_invalid(form)


class OrganizerPlanDelete(
    OrganizerPermissionRequiredMixin, SeatingPlanDetailMixin, CompatDeleteView
):
    model = SeatingPlan
    template_name = "seatmap/organizer/delete.html"
    context_object_name = "seatingplan"
    permission = "can_change_organizer_settings"

    def get_context_data(self, **kwargs: Any):
        ctx = super().get_context_data(**kwargs)

        ctx["inuse"] = self.is_in_use()

        return ctx

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        if self.is_in_use():
            messages.error(
                self.request,
                _(
                    "You cannot delete the seating plan because it is used in at least one of your events."
                ),
            )
            return HttpResponseRedirect(self.get_success_url())

        self.object = self.get_object()
        self.object.log_action(
            "pretix_manualseats.seatingplan.deleted", user=self.request.user
        )
        self.object.delete()
        messages.success(request, _("The selected plan has been deleted."))
        self.request.organizer.cache.clear()
        return HttpResponseRedirect(self.get_success_url())
