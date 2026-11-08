"""Address variants: other valid spellings of the same address (street suffix, direction, punctuation, optional unit line).
Every variant keeps the same number, street name, city, state and ZIP, so the post office resolves it to the same place."""
import itertools
import random
import re

_SUFFIX = {"street": ("st",), "avenue": ("ave", "av"), "road": ("rd",), "drive": ("dr",), "lane": ("ln",), "court": ("ct",), "boulevard": ("blvd",),
           "circle": ("cir",), "place": ("pl",), "terrace": ("ter",), "parkway": ("pkwy",), "trail": ("trl",), "highway": ("hwy",), "way": ()}
_DIRS = {"north": "n", "south": "s", "east": "e", "west": "w"}
FORMS = {}
for full, abbr in _SUFFIX.items():
    forms = [full.title()] + [a.title() for a in abbr] + [a.title() + "." for a in abbr]
    for w in (full,) + abbr:
        FORMS[w] = forms
        FORMS[w + "."] = forms
for full, a in _DIRS.items():
    forms = [full.title(), a.upper(), a.upper() + "."]
    for w in (full, a):
        FORMS[w] = forms
        FORMS[w + "."] = forms
UNIT_STYLES = ["Apt {}", "Unit {}", "#{}", "Ste {}", "Apt. {}", "Unit #{}"]
_norm = lambda s: re.sub(r"[\W_]+", "", s or "").lower()


def street_forms(line1):
    words = line1.split()
    opts = [FORMS.get(w.lower(), [w]) for w in words]
    out = {" ".join(c) for c in itertools.islice(itertools.product(*opts), 300)}
    out |= {o.replace(".", "") for o in out}
    return sorted(out)


def generate(line1, line2="", count=10, seed=None, use_units=True, units=None, keep_original=False):
    """Returns up to `count` distinct (line1, line2) pairs. `units` = real unit values to hand out instead of invented ones."""
    rng = random.Random(seed)
    line2 = (line2 or "").strip()
    base = street_forms(line1)
    pool = []
    unit_vals = units or [str(i) for i in range(1, 10)] + list("ABCD")
    m = re.match(r"^\s*(?:[A-Za-z]{2,6}\.?|#)\s*#?\s*(\S.*)$", line2) if line2 else None
    for l1 in base:
        pool.append((l1, line2))
        if use_units and m:
            pool += [(l1, st.format(m.group(1))) for st in UNIT_STYLES[:5]]
        elif use_units and not line2:
            pool += [(l1, st.format(v)) for st in UNIT_STYLES for v in unit_vals]
    rng.shuffle(pool)
    seen = {(_norm(line1), _norm(line2))}
    out = [(line1, line2)] if keep_original else []
    for l1, l2 in pool:
        k = (_norm(l1), _norm(l2))
        if k in seen:
            continue
        seen.add(k)
        out.append((l1, l2))
        if len(out) >= count:
            break
    return out[:count]
