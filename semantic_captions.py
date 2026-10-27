"""Russian lyric caption phrasing from Whisper's word-level timings.

Priorities: (1) don't break a grammatical unit, (2) respect vocal pauses and
repeated chorus starts, (3) keep captions short and readable. This module does
not invent or correct lyrics; Whisper can still recognize singing incorrectly.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

MICRO = 1_000_000

# Captions must NEVER end with a comma, including text loaded from a saved SRT.
def clean_caption(text: str) -> str:
    text = re.sub(r'\s+', ' ', str(text)).strip()
    text = re.sub(r'\s+([,，.!?;:])', r'\1', text)
    return re.sub(r'[,，]+\s*$', '', text).strip()

FUNCTION_END = {
    'в','во','на','над','под','за','из','от','до','без','для','при','об','о',
    'с','со','к','ко','по','про','у','перед','между','через','сквозь',
    'не','ни','бы','б','же','ли','то','из-за','из-под',
    'и','или','а','но','да','что','чтобы','чтоб','как','где','когда',
    'если','ведь','хоть','хотя','потому','пока','пускай','пусть',
    'я','ты','мы','вы','он','она','они','оно','мой','моя','мои','твой','твоя',
    'этот','эта','это','эти','все','всё','свой','своя','свои',
}
CLAUSE_OPEN = {
    'но','а','зато','однако','потом','тогда','теперь','снова','ведь',
    'хотя','если','когда','пока','чтобы','чтоб','потому','поэтому',
    'где','куда','откуда','почему','зачем','который','которая','которые',
    'которое','пусть','лишь','словно','будто','только','даже',
}
POSTPOSITIONS = {'же','ли','бы','б','то','нибудь','ка','таки'}
# Common (not exhaustive) verbs which normally want a following object/complement.
EXPECT_COMPLEMENT = {
    'хочу','хочет','хочешь','хотят','желаю','желаешь','желаем','ищу',
    'ищет','люблю','любишь','любит','жду','ждёт','ждет','вижу','видит',
    'слышу','слышит','помню','помнит','знаю','знает','найду','нашёл',
    'давай','дайте','дай','хотел','хотела','мечтаю','мечтает',
}
PRONOUNS = {'меня','тебя','его','её','ее','нас','вас','им','их','нам','вам','мне','тебе'}

@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str
    probability: float | None = None
    segment_start: bool = False


def _token(text: str) -> str:
    return re.sub(r'^[^\wёЁ-]+|[^\wёЁ-]+$', '', text, flags=re.UNICODE).lower()


def _pause(words: list[Word], index: int) -> float:
    return max(0.0, words[index].start - words[index - 1].end) if index else 0.0


def _adjective_like(token: str) -> bool:
    # Only high-confidence endings; don't use this as a general grammar parser.
    if len(token) < 5: return False
    return token.endswith(('ый','ий','ой','ая','яя','ое','ее','ые','ие',
                           'ого','его','ому','ему','ую','юю','ыми','ими'))


def _refrain_starts(words: list[Word]) -> set[int]:
    """Detect repeated 2–3 word chorus motifs; reward boundaries at repeat starts."""
    toks = [_token(w.text) for w in words]
    occurrences: dict[tuple[str, ...], list[int]] = {}
    for i in range(len(toks) - 1):
        key = (toks[i], toks[i + 1])
        if all(len(t) > 1 for t in key):
            occurrences.setdefault(key, []).append(i)
    result=set()
    for indices in occurrences.values():
        if len(indices) < 2: continue
        for i in indices:
            if i > 0: result.add(i)
    return result


def _boundary_cost(words: list[Word], pos: int, refrains: set[int]) -> float:
    """Cost of ending the current subtitle *before* words[pos]. Lower is better."""
    if pos >= len(words): return 0.0
    previous, following = words[pos - 1], words[pos]
    left, right = _token(previous.text), _token(following.text)
    silence = _pause(words,pos)
    cost = 4.4

    if silence >= .55: cost -= 16
    elif silence >= .32: cost -= 11
    elif silence >= .20: cost -= 7
    elif silence >= .11: cost -= 4.0
    elif silence >= .06: cost -= 1.4

    if re.search(r'[.!?…][\"»]?$',previous.text): cost -= 11
    elif re.search(r'[,，;:][\"»]?$',previous.text): cost -= 6
    if right in CLAUSE_OPEN: cost -= 6.5 if right in {'чтобы','чтоб','но','а','где','когда'} else (4 if silence >= .05 else 2.1)
    if right == 'и' and silence >= .10: cost -= 4.5
    if pos in refrains: cost -= 7
    if following.segment_start and silence >= .08: cost -= 2.5
    if following.text[:1].isupper() and pos > 0 and silence >= .04: cost -= 1.2

    # Splitting a function word from what it modifies is markedly worse than a
    # slightly long subtitle. Exceptions require an unmistakable long silence.
    if left in FUNCTION_END: cost += 26 if silence < .70 else 6
    if right in POSTPOSITIONS: cost += 16
    if _adjective_like(left) and right not in CLAUSE_OPEN: cost += 17
    if left in EXPECT_COMPLEMENT and right not in CLAUSE_OPEN: cost += 13
    if left in {'в','на','за','без','до','для','по','от','у','с','из'} and right in PRONOUNS:
        cost += 10
    return cost


MAX_LINE_CHARS = 25
MAX_LINE_WORDS = 4
MAX_CAPTION_WORDS = 7


def two_line_layout(text: str) -> str | None:
    """Layout a subtitle on <=2 lines within a conservative vertical safe area.

    Try not to split a preposition/conjunction/adjective from the next word.
    None means the spoken phrase must be split into separate timed captions.
    """
    raw=clean_caption(text)
    terms=raw.split()
    if not terms: return None
    if len(terms)>MAX_CAPTION_WORDS: return None
    if len(terms)<=MAX_LINE_WORDS and len(raw)<=MAX_LINE_CHARS:return raw
    candidates=[]
    for cut in range(1,len(terms)):
        left=' '.join(terms[:cut]);right=' '.join(terms[cut:])
        if len(left)>MAX_LINE_CHARS or len(right)>MAX_LINE_CHARS:continue
        if cut>MAX_LINE_WORDS or len(terms)-cut>MAX_LINE_WORDS:continue
        ltok=_token(terms[cut-1]);rtok=_token(terms[cut])
        penalty=abs(len(left)-len(right))*.13
        if ltok in FUNCTION_END:penalty+=40
        if _adjective_like(ltok) and rtok not in CLAUSE_OPEN:penalty+=25
        if ltok in EXPECT_COMPLEMENT:penalty+=22
        if rtok in POSTPOSITIONS:penalty+=18
        if rtok in CLAUSE_OPEN:penalty-=7
        candidates.append((penalty,cut,left,right))
    if not candidates:return None
    _,_,a,b=min(candidates)
    # No terminal comma at a visual line break either.
    return a.rstrip(',，')+'\n'+b.rstrip(',，')


def phrase_rows(raw_words: list[tuple], duration_us: int) -> list[tuple[int,int,str]]:
    """Convert word-level timestamps into short, readable, nonoverlapping captions."""
    length_sec = max(0.0,duration_us/MICRO)
    words: list[Word] = []
    for row in raw_words:
        if len(row) < 3: continue
        try: st, en = float(row[0]),float(row[1])
        except (TypeError,ValueError):continue
        text = str(row[2]).strip()
        if not text or not math.isfinite(st) or not math.isfinite(en):continue
        if st < 0 or en <= st or st > length_sec + .3: continue
        if text.lower() in {'[музыка]','[music]','♪','♫'}:continue
        p = float(row[3]) if len(row)>3 and row[3] is not None else None
        is_segment_start=bool(row[4]) if len(row)>4 else False
        words.append(Word(st,min(en,length_sec),text,p,is_segment_start))
    words.sort(key=lambda x:(x.start,x.end))
    if not words:return []
    n=len(words)
    refrains=_refrain_starts(words)
    boundaries={i:_boundary_cost(words,i,refrains) for i in range(1,n)}
    costs=[float('inf')]*(n+1)
    predecessors=[-1]*(n+1)
    costs[0]=0.0

    for stop in range(1,n+1):
        for start in range(max(0,stop-MAX_CAPTION_WORDS),stop):
            count=stop-start
            duration=words[stop-1].end-words[start].start
            candidate=clean_caption(' '.join(w.text for w in words[start:stop]))
            chars=len(candidate)
            if two_line_layout(candidate) is None:continue
            if count > 1 and duration > 4.1: continue
            penalty=0.0
            if duration > 2.5: penalty += 4.2*(duration-2.5)**2
            if duration > 3.2: penalty += 16*(duration-3.2)
            if chars > 32: penalty += .45*(chars-32)**2
            if count > 5: penalty += 2.0*(count-5)**2
            if count == 1 and n > 1: penalty += 10
            elif count == 2 and n > 2: penalty += 1.7
            if duration < .55 and stop != n and n > 3: penalty += 5
            if 1.1 <= duration <= 2.9 and 3 <= count <= 6: penalty -= 1

            # Even if the caption fits, don't swallow distinct sung clauses.
            for mid in range(start+1,stop):
                gap=_pause(words,mid)
                if gap >= .55: penalty += 22
                elif gap >= .32: penalty += 12
                elif gap >= .20: penalty += 5
                if re.search(r'[.!?…]$',words[mid-1].text): penalty += 10
                elif re.search(r'[,，;:]$',words[mid-1].text): penalty += 4.5
                if mid in refrains: penalty += 8

            split_cost=boundaries.get(stop,0.0)
            proposed=costs[start]+penalty+split_cost
            if proposed < costs[stop]:
                costs[stop]=proposed
                predecessors[stop]=start

    spans=[]
    stop=n
    while stop>0:
        start=predecessors[stop]
        if start<0:start=stop-1
        spans.append((start,stop));stop=start
    spans.reverse()

    output=[]
    for i,(start,stop) in enumerate(spans):
        first,last=words[start],words[stop-1]
        begin=max(0.0,first.start-.035)
        end=min(length_sec,last.end+.055)
        if i<len(spans)-1:
            following=words[spans[i+1][0]]
            end=min(end,(last.end+following.start)/2 if following.start > last.end
                    else following.start)
        if output:begin=max(begin,output[-1][1]/MICRO)
        if end-begin<.12:end=min(length_sec,begin+.14)
        content=clean_caption(' '.join(w.text for w in words[start:stop]))
        if content and end>begin:output.append((round(begin*MICRO),round(end*MICRO),content))
    # Repaired overlaps can occur if Whisper assigns a word overlapping times.
    fixed=[]
    for start,end,caption in output:
        if fixed and start<fixed[-1][1]:
            pstart,pend,ptext=fixed[-1]
            if start-pstart >= 130_000:fixed[-1]=(pstart,start,ptext)
            else:start=pend
        if end-start>=110_000:fixed.append((start,end,caption))
    return fixed
