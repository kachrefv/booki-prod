# pretixkonnect/payment.py

from pretix.base.payment import BasePaymentProvider

from django.urls import reverse
from collections import OrderedDict
from django.utils.translation import gettext_lazy as _
from django.template.loader import get_template
from django import forms
import requests

class KonnectPaymentProvider(BasePaymentProvider):
    identifier = 'konnect'
    verbose_name = 'Konnect'


    @property
    def settings_form_fields(self):
        return OrderedDict(
            list(super().settings_form_fields.items()) + [
                ('api_key',
                 forms.CharField(
                     label=_("Konnect API Key"),
                     required=True,
                     widget=forms.TextInput(attrs={'placeholder': 'API key from your Konnect account'})
                 )),
                ('base_url',
                 forms.URLField(
                     label=_("Konnect API Base URL"),
                     required=True,
                     initial="https://api.sandbox.konnect.network/api/v2"
                 ))
            ]
        )

    def checkout_prepare(self, request, cart):
        # Example: Create a payment through Konnect API
        # amount = int(cart['total'] * 1000)
        # pay_url, payment_ref = self.initiate_payment(
        #     order="cart['order']",
        #     amount=amount,
        #     first_name="cart['order'].invoice_address.contact_name.split()[0]",
        #     last_name="' '.join(cart['order'].invoice_address.contact_name.split()[1:])",
        #     email="cart['order'].email",
        #     phone="cart['order'].invoice_address.phone",
        #     order_id= str(self.event)+"  "+ str(cart['itemcount'])+" Tickets"
        # )
        # # Save the reference info in session
        # request.session['payment_konnect_id'] = payment_ref
        # # Return a redirect URL if needed
        # return pay_url
        request.session['payment_konnect_cart_total'] = str(cart['total'])
        request.session['payment_konnect_itemcount'] = str(cart['itemcount'])
        return True
    
    def execute_payment(self, request, payment):
        """
        After the user confirms the order, Pretix calls this.
        Here we initiate the payment at Konnect and return the redirect URL.
        """
        # Convert amount to millimes (TND subunit)
        amount = int(payment.amount * 1000)

        # Safely extract order/customer details
        order = payment.order
        first_name = order.invoice_address.name_parts.get("given", "") if order.invoice_address else ""
        last_name = order.invoice_address.name_parts.get("family", "") if order.invoice_address else ""
        email = order.email
        # phone = order.invoice_address.phone if order.invoice_address else ""
        # order_id = f"{self.event.slug}-{payment.local_id}"
        order_id = order.code
        # request.session['payment_konnect_payment'] = payment_ref
        request.session['payment_konnect_order'] = order.pk
        print(f"***************     Order Id : {order_id}      ***********")

        # Call Konnect API
        pay_url, payment_ref = self.initiate_payment(
            payment=payment.pk,
            amount=amount,
            first_name=first_name,
            last_name=last_name,
            email=email,
            # phone=phone,
            phone="96897689",
            order_id=order_id,
        )

        # Store reference in payment.info for later verification
        payment.info = {
            "payment_ref": payment_ref,
            "pay_url": pay_url
        }
        payment.save(update_fields=["info"])

        # Redirect user to Konnect payment page
        return pay_url

    API_KEY = '68a85a7b22c44ea00bba2332:XbObgQM6THXendK54td8QtSR5alb'  # replace with your actual API key

    def initiate_payment(self, payment, amount, first_name, last_name, email, phone, order_id):

        
        url = "https://api.sandbox.konnect.network/api/v2/payments/init-payment"
        headers = {
            "x-api-key": self.API_KEY
        }
        body = {
            "receiverWalletId": "68a85a7d22c44ea00bba2349",  # your receiver wallet ID
            "token": "TND",  # currency
            "amount": amount,  # in Millimes
            "type": "immediate",
            "description": f"Order {order_id}",
            "acceptedPaymentMethods": ["wallet", "bank_card", "e-DINAR"],
            "lifespan": 30,
            "checkoutForm": True,
            "addPaymentFeesToAmount": True,
            "firstName": first_name,
            "lastName": last_name,
            "phoneNumber": phone,
            "email": email,
            "orderId": f"{order_id}-{payment}",
            "webhook": "http://127.0.0.1:8000/api/payment/konnect/notification",
            "theme": "dark",
        }
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        response = requests.post(url, headers=headers,json=body,timeout=30 )
        
        print(response.json())
        if response.status_code == 200:
            data = response.json()
            pay_url = data.get('payUrl')
            print(pay_url)
            payment_ref = data.get('paymentRef')
            return pay_url, payment_ref
        else:
            # handle error
            raise Exception(f"Konnect API error: {response.text}")

    def payment_prepare(self, request, payment_obj):   
        print("payment prepaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaare!!!!!!!")        
        request.session['payment_konnect_payment'] = payment_obj.pk
        return True#self._create_payment(request, payment)
        

    # def execute_payment(self, request, payment):

    #     print("+++++++++++++++++++++++execute payment is entered+++++++++++++++++++++++++++++++")
    #     # assuming you stored paymentRef during checkout
    #     payment_ref = payment.info_data.get('paymentRef')
    #     # Possibly verify payment status with API if needed
    #     # or confirm directly if webhook handles it
    #     payment.confirm()

    def payment_is_valid_session(self, request, total=None):
        # Implement validation logic here
        # For example, check that required data exists in session or request
        # For initial testing, just return True
        print("here not implemented!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        return True


    def payment_url(self, request, payment):
        # Generate the Konnect checkout URL with redirect back to your plugin
        redirect_uri = request.build_absolute_uri(reverse('pretixkonnect:konnect_callback'))
        checkout_url = 'https://sandbox.konnect.network/checkout'  # Replace with real URL
        checkout_url += '?redirect_uri=' + redirect_uri
        # Add other params here if needed
        return checkout_url

    def checkout_confirm_render(self, request) -> str:
        """
        Returns the HTML displayed when the user selected Konnect
        on the 'confirm order' page.
        """
        template = get_template('pretixkonnect/checkout_payment_confirm.html')
        ctx = {
            'request': request,
            'event': self.event,
            'settings': self.settings,
        }
        return template.render(ctx)


    # Optionally, implement other methods as needed
