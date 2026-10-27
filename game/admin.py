from django.contrib import admin

from .models import CustomQuestion, Question

admin.site.register(Question)
admin.site.register(CustomQuestion)
