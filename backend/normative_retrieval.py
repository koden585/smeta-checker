"""Content-driven page/block retrieval; no expected VOR quantity or page numbers."""
import math
import re
from collections import Counter

def terms(text):
    # Share normalization with matching; "нижнего" and "нижний" must not
    # become different five-character prefixes in the normative search.
    from audit_core import _terms
    return _terms(text) | set(re.findall(r'\d+/\d+(?:[.,]\d+)?', str(text)))


def blocks(text, size=2400):
    """Overlapping windows retain neighbouring headings and continuation offsets."""
    if len(text) <= size:
        return [(0, text)]
    return [(offset, text[offset:offset+size]) for offset in range(0, len(text), size-400)]


class DocumentSearch:
    def __init__(self, texts):
        self.texts = texts
        self.rows = [(p+1, offset, text, terms(text)) for p, page in enumerate(texts) for offset, text in blocks(page)]
        counts = Counter(t for _, _, _, ts in self.rows for t in ts)
        self.weights = {t: math.log(1+len(self.rows)/n) for t, n in counts.items()}

    def search(self, query, *, tables=False, limit=5):
        wanted = terms(query)
        ranked = []
        for page, offset, text, ts in self.rows:
            overlap = wanted & ts
            table = bool(re.search(r'ведомост|объем|площад|количеств|итого|всего', text, re.I))
            numeric_density = min(5, len(re.findall(r'\d+[.,]\d+', text)) / 8)
            score = sum(self.weights[t] for t in overlap)
            if tables:
                if not table:
                    continue
                score += 4 + numeric_density
            elif not overlap:
                continue
            ranked.append((score, page, offset, text))
        ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
        found, seen = [], set()
        for score, page, offset, text in ranked:
            if page in seen:
                continue
            seen.add(page)
            found.append(dict(page=page, offset=offset, preview=text[:450], score=round(score, 2)))
            if len(found) == limit:
                break
        return found
