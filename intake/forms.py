"""Forms for mock incoming leads."""

from __future__ import annotations

from django import forms


class LeadForm(forms.Form):
    name = forms.CharField(max_length=255)
    phone = forms.CharField(max_length=64)
    email = forms.EmailField(required=False)
    text = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    source = forms.CharField(max_length=120, initial="site")
    website = forms.CharField(required=False, widget=forms.HiddenInput)
