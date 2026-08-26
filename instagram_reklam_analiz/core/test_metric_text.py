from django.test import SimpleTestCase

from core.utils.metric_text import format_metric_text_tr, format_tr_decimal


class MetricTextFormattingTests(SimpleTestCase):
    def test_formats_two_decimals_and_turkish_thousands(self):
        self.assertEqual(format_tr_decimal("13.4557162515268178796171458"), "13,46")
        self.assertEqual(format_tr_decimal("16169.25"), "16.169,25")
        self.assertEqual(format_tr_decimal("1659000"), "1.659.000,00")

    def test_formats_values_inside_persisted_task_message(self):
        text = (
            "Mevcut değer: 16169.25 Önceki değer: 9592.45 "
            "Değişim: %68.558765"
        )
        self.assertEqual(
            format_metric_text_tr(text),
            "Mevcut değer: 16.169,25 Önceki değer: 9.592,45 Değişim: %68,56",
        )

    def test_existing_turkish_format_is_stable(self):
        self.assertEqual(format_metric_text_tr("Mevcut değer: 16.169,25"), "Mevcut değer: 16.169,25")
