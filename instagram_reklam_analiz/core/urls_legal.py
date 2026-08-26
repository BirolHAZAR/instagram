from django.urls import path

from core.views.legal import legal_document_detail, legal_document_index


urlpatterns = [
    path("hukuk/", legal_document_index, name="legal_document_index"),
    path("hukuk/<slug:slug>/", legal_document_detail, name="legal_document_detail"),
]
