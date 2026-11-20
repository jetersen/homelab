"""Source-preservation and stable identity checks for the T3 search adapter."""

import unittest

from t3_search import conversation


class ConversationTests(unittest.TestCase):
    def test_export_preserves_identity_links_and_excludes_streaming_messages(self):
        thread = {
            "id": "thread-1",
            "title": "Example",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-02T00:00:00Z",
            "settledOverride": "settled",
        }

        def message(mid, role, text, streaming=False):
            return {
                "id": mid,
                "role": role,
                "text": text,
                "streaming": streaming,
                "createdAt": "2026-01-01T00:00:00Z",
            }

        result = conversation(
            thread,
            [
                message("u", "user", "Question"),
                message("a", "assistant", "Answer"),
                message("live", "assistant", "Partial", True),
            ],
            "environment",
        )
        self.assertEqual(result["id"], "t3-thread-1")
        self.assertEqual(list(result["mapping"]), ["u", "a"])
        self.assertEqual(result["mapping"]["a"]["parent"], "u")
        self.assertEqual(result["mapping"]["u"]["children"], ["a"])
        self.assertIn(
            "t3-thread://v2/environment/thread-1",
            result["mapping"]["u"]["message"]["content"]["parts"][0],
        )
        self.assertIn("marked settled", result["title"])
        self.assertEqual(result["current_node"], "a")
        self.assertEqual(thread["title"], "Example")

    def test_unmarked_is_reviewable_not_claimed_incomplete(self):
        thread = {
            "id": "thread-2",
            "title": "Example",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }
        self.assertIn("review in T3", conversation(thread, [], "e")["title"])


if __name__ == "__main__":
    unittest.main()
