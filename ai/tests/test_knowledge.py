from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from ai.knowledge import retrieve_knowledge_context


@override_settings(AI_KB_ENABLED=True, AI_KB_MAX_CHUNKS=5, AI_KB_MAX_CHARS=6000)
class KnowledgeRetrievalTests(SimpleTestCase):
    def test_retrieves_catalog_entry_for_model(self):
        context = retrieve_knowledge_context("Сколько стоит Haval Jolion? Добавь ссылку")

        self.assertIn("Haval Jolion", context)
        self.assertIn("https://skayavto.ru/catalog/haval/jolion", context)

    def test_retrieves_dealership_contacts(self):
        context = retrieve_knowledge_context("Какой адрес и график работы салона?")

        self.assertIn("Дмитровское шоссе", context)
        self.assertIn("9:00", context)

    def test_retrieves_credit_knowledge(self):
        context = retrieve_knowledge_context("Какие есть условия кредита и первоначальный взнос?")

        self.assertIn("Кредит", context)

    def test_current_message_outweighs_old_dialog_topics(self):
        history = (
            "клиент: Какой банк кредитует?\n"
            "менеджер: Расскажем про кредит, банки, ставку и первоначальный взнос.\n"
            "клиент: у вас есть BMW?"
        )

        context = retrieve_knowledge_context(history, focus_query="у вас есть BMW?")

        self.assertIn("Audi, BMW, Kia", context)
        self.assertLess(context.index("BMW"), context.index("Кредит"))

    @override_settings(AI_KB_ENABLED=False)
    def test_can_disable_knowledge_context(self):
        self.assertEqual(retrieve_knowledge_context("Haval Jolion"), "")

    def test_empty_knowledge_base_returns_empty_context(self):
        with patch("ai.knowledge._load_chunks", return_value=()):
            context = retrieve_knowledge_context("Haval Jolion")

        self.assertEqual(context, "")
