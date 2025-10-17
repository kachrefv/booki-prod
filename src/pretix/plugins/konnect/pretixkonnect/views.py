# pretixkonnect/views.py

from django.http import HttpResponse


# your_app/views.py
from django.views.decorators.csrf import csrf_exempt
from pretix.base.models import Order, OrderPayment, OrderRefund, Quota
from pretix.base.payment import PaymentException
from pretix.control.permissions import event_permission_required
from pretix.helpers.http import redirect_to_url
from pretix.multidomain.urlreverse import eventreverse
from django.http import JsonResponse
from django.conf import settings
from django.urls import reverse
from pretixkonnect.models import KonnectPaymentLink
import requests
import logging

from pretix.multidomain.urlreverse import eventreverse

logger = logging.getLogger(__name__)

@csrf_exempt
def konnect_webhook(request):
    if request.method == 'GET':
        payment_ref = request.GET.get('payment_ref')
        if not payment_ref:
            return JsonResponse({"error": "Missing payment_ref"}, status=400)

        # Log received payment_ref
        print(f"Received webhook for payment_ref: {payment_ref}")

        # Fetch payment status from Konnect
        try:

            payment_info = get_payment_details(payment_ref)
            payment_status=payment_info.get('status')
            order_code, payment_id = payment_info.get('orderId').split('-')

            payment = OrderPayment.objects.get(pk=int(payment_id))
            print(payment_info.get('orderId'))

            #order = Order.
            #if payment_ref:
            #    payment = OrderPayment.objects.get(pk=payment_ref)
            #else:
            #    payment = None

            #rso = KonnectPaymentLink.objects.select_related('order').get(payment_ref=payment_ref)
            #order = rso.order
            #payment = rso.payment
            # Example: mark order as paid if status is 'paid'
            if payment_status == 'completed':
                try:
                    # Retrieve the order associated with this payment_ref
                    print("entered//////////////////////////////////////////////")
                    payment.confirm()
                    #order.mark_as_paid()  # Assuming you have this method on your Order model
                    #payment.order.log_action('pretix.plugins.konnect.payment', data={
                    #    "message": "Payment completed",
                    #    "payment_ref": payment_ref
                    #})

                    #print(f"Order {payment.order.id} marked as paid for payment_ref {payment_ref}")

                    # Redirect to the order confirmation page
                    # Ensure 'order' and 'secret' params are correct
                    return redirect_to_url(reverse('presale:event.order', kwargs={
                        'order': payment.order.code,
                        'secret': payment.order.secret,
                        'event': payment.order.event.slug,
                        'organizer': payment.order.organizer.slug
                    }) + ('?paid=yes') if payment.order.status == Order.STATUS_PAID else '')

                except Order.DoesNotExist:
                    logger.error(f"Order not found for payment_ref: {payment_ref}")
                    return JsonResponse({"error": "Order not found"}, status=404)
                
            elif payment_status == 'failed':
                # Your code for failed payment
                pass
            # Add more conditions as needed

            return redirect_to_url(reverse('presale:event.order', kwargs={
                'order': payment.order.code,
                'secret': payment.order.secret,
                'event': payment.order.event.slug,
                'organizer': payment.order.organizer.slug
                }))# + ('?paid=yes') if payment.order.status == Order.STATUS_PAID else ''
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return JsonResponse({"error": str(e)}, status=500)

    else:
        return JsonResponse({"error": "Invalid method"}, status=405)

def get_payment_details(payment_ref):
    # Call Konnect API to get payment info
    api_key = settings.KONNECT_API_KEY  # Store your API key securely
    url = f"https://api.sandbox.konnect.network/api/v2/payments/{payment_ref}"  # Confirm actual URL from API docs

    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    response = requests.get(url, headers=headers, timeout=10)
    print("$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$")
    print(response.json())

    if response.status_code == 200:
        data = response.json()
        # Extract payment status from nested structure
        payment_info = data.get('payment')
        print("**********************************************")
        print(payment_info.get('status'))
        if payment_info:
            return payment_info
        else:
            raise Exception('No payment info found in response')
    else:
        raise Exception(f"Failed to get payment details: {response.text}")



@csrf_exempt
def konnect_settings_view(request):
    # You can customize this page with your settings form later
    return HttpResponse("Konnect plugin settings page")
