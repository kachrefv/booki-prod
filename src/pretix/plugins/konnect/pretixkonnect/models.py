from django.db import models
from pretix.base.models import Order, OrderPayment

class KonnectPaymentLink(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    payment = models.ForeignKey(OrderPayment, on_delete=models.CASCADE)
    payment_ref = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
