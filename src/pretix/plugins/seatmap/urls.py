from django.urls import path

from . import views, api

# The event_patterns list is automatically included in the event's URL patterns
# by pretix. It should contain all URLs that need to be aware of the event
# and organizer, but without the <organizer>/<event> parts in the URL.

event_patterns = [
    path("seatmap/api/data/", api.SeatmapDataAPIView.as_view(), name="seatmap.api.data"),
    path(
        "manualseats/select/",
        views.SeatSelectionView.as_view(),
        name="select",
    ),
    path(
        "checkout/seats/",
        views.CheckoutSeatSelectionView.as_view(),
        name="checkout.seats",
    ),
]

# The urlpatterns list is automatically included in the control panel URL patterns
# by pretix. It should contain all URLs that are part of the backend.

urlpatterns = [
    # Event-level control panel URLs
    path(
        "control/event/<str:organizer>/<str:event>/manualseats/",
        views.EventIndex.as_view(),
        name="event.index",
    ),
    path(
        "control/event/<str:organizer>/<str:event>/manualseats/mapping/",
        views.EventMapping.as_view(),
        name="event.mapping",
    ),
    path(
        "control/event/<str:organizer>/<str:event>/manualseats/assign/",
        views.EventAssign.as_view(),
        name="event.assign",
    ),
    # Organizer-level control panel URLs
    path(
        "control/organizer/<str:organizer>/manualseats/",
        views.OrganizerSeatingPlanList.as_view(),
        name="organizer.index",
    ),
    path(
        "control/organizer/<str:organizer>/manualseats/add",
        views.OrganizerPlanAdd.as_view(),
        name="organizer.add",
    ),
    path(
        "control/organizer/<str:organizer>/manualseats/<int:seatingplan>/edit",
        views.OrganizerPlanEdit.as_view(),
        name="organizer.edit",
    ),
    path(
        "control/organizer/<str:organizer>/manualseats/<int:seatingplan>/delete",
        views.OrganizerPlanDelete.as_view(),
        name="organizer.delete",
    ),
]
