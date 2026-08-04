from django.contrib import admin

# Register your models here.
from .models import CoupleSession, Question, CustomQuestion

admin.site.register(CoupleSession)
admin.site.register(Question)
admin.site.register(CustomQuestion)
