"""Where a couple space's cards come from: the shared question bank plus the
couple's own custom questions."""

from game.models import CustomQuestion, Question


def card_for_question(question):
    custom = isinstance(question, CustomQuestion)
    return {
        "key": f"{'c' if custom else 'q'}:{question.pk}",
        "text": question.text,
        "mode": question.mode,
        "kind": question.kind,  # "truth" or "dare" in Truth or Dare, else "".
        "custom": custom,
    }


class DatabaseCards:
    """The card source for one couple space and question mode."""

    def __init__(self, couple, mode):
        self.couple, self.mode = couple, mode

    def all(self):
        bank = Question.objects.all()
        custom = CustomQuestion.objects.filter(space=self.couple)
        if self.mode != "mixed":
            bank, custom = bank.filter(mode=self.mode), custom.filter(mode=self.mode)
        cards, seen = [], set()
        for question in [*bank.order_by("pk"), *custom.order_by("created_at")]:
            text = question.text.strip().casefold()
            if text not in seen:  # The same text only once.
                seen.add(text)
                cards.append(card_for_question(question))
        return cards

    def get(self, key):
        kind, _, pk = (key or "").partition(":")
        if not pk.isdigit():
            return None
        if kind == "q":
            question = Question.objects.filter(pk=pk).first()
        elif kind == "c":
            question = CustomQuestion.objects.filter(pk=pk, space=self.couple).first()
        else:
            return None
        return card_for_question(question) if question else None
