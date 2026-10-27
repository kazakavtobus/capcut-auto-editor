"""Offline unit tests for caption reflow. No Whisper model needed."""
import unittest
from semantic_captions import phrase_rows, clean_caption


def sample(items):
    return phrase_rows([(start,end,word,.9,False) for word,start,end in items], 8_000_000)


class SemanticCaptionsTests(unittest.TestCase):
    def test_clause_boundary_before_gde(self):
        rows=sample([
            ('Я',0,.22), ('хочу',.24,.55), ('жить',.57,.86),
            ('в',.87,.94), ('раю,',.96,1.25), ('где',1.34,1.58),
            ('бы',1.60,1.73), ('ни',1.75,1.84), ('был',1.85,2.12),
        ])
        self.assertEqual([x[2] for x in rows],['Я хочу жить в раю','где бы ни был'])

    def test_conjunction_doesnt_end_group(self):
        rows=sample([
            ('Душа',0,.33), ('хочет',.35,.62), ('покоя,',.65,1.06),
            ('но',1.17,1.32), ('снова',1.35,1.62), ('зовёт',1.65,1.96),
            ('дорога',1.99,2.39),
        ])
        self.assertEqual([x[2] for x in rows],['Душа хочет покоя','но снова зовёт дорога'])
        self.assertTrue(all(not x[2].endswith(' но') for x in rows))

    def test_short_function_words_stay_attached(self):
        rows=sample([('И',0,.13),('я',.16,.34),('в',.4,.45),
                     ('городе',.49,.83),('без',.85,1.0),('тебя',1.04,1.32)])
        self.assertEqual([x[2] for x in rows],['И я в городе без тебя'])

    def test_big_pause_creates_boundary(self):
        rows=sample([('Там',0,.2),('где',.22,.4),('тихо',.4,.73),
                     ('Я',1.6,1.8),('вернусь',1.9,2.3)])
        self.assertEqual(len(rows),2)
        self.assertTrue(rows[0][1]<=rows[1][0])

    def test_preserves_all_words(self):
        words=[('Я',.01,.25),('не',.27,.42),('знаю,',.45,.8),('но',.9,1.04),
               ('ты',1.06,1.2),('знаешь',1.25,1.8),('всё',2.0,2.4)]
        rows=sample(words)
        self.assertEqual(' '.join(x[2] for x in rows),' '.join(x[0] for x in words).replace('знаю,','знаю'))
        self.assertTrue(all(a[1] <= b[0] for a,b in zip(rows,rows[1:])))

    def test_vocal_chorus_clauses(self):
        # A regression case mirroring the user's troublesome refrain phrasing.
        words = [
            ('Душа',0,.35),('хочет',.36,.72),('водки',.76,1.20),
            ('и',1.32,1.50),('чистое',1.53,1.85),('небо,',1.88,2.26),
            ('Зарплату',2.95,3.25),('за',3.28,3.48),('сотку',3.53,4.01),
            ('жить',4.45,4.76),('в',4.78,4.88),('раю,',4.92,5.16),
            ('где',5.25,5.42),('бы',5.45,5.54),('ни',5.56,5.65),('был',5.68,5.95),
            ('Душа',6.10,6.45),('хочет',6.46,6.80),('пива',6.85,7.15),
            ('чтобы',7.18,7.37),('было',7.40,7.64),('красиво',7.68,8.1),
        ]
        rows=phrase_rows([(a,b,t,.95, i in (0,6,9,16))
                          for i,(t,a,b) in enumerate(words)], 8_900_000)
        self.assertEqual([r[2] for r in rows],[
            'Душа хочет водки','и чистое небо','Зарплату за сотку',
            'жить в раю','где бы ни был','Душа хочет пива',
            'чтобы было красиво'])
        self.assertTrue(all(not r[2].endswith(',') for r in rows))

    def test_never_leaves_terminal_comma(self):
        for value, expected in [('душа хочет,','душа хочет'),
                                ('всё будет,  ','всё будет'),
                                ('раз, два, три,','раз, два, три'),
                                ('наша песня，','наша песня')]:
            self.assertEqual(clean_caption(value),expected)

    def test_adjective_and_noun_not_split(self):
        rows=sample([('и',0,.2),('чистое',.21,.56),('небо',.6,.92),
                     ('над',1.1,1.3),('нами',1.31,1.6)])
        self.assertFalse(any(r[2] in {'и чистое','над'} for r in rows))

    def test_clause_and_silence_timing(self):
        rows=sample([('Куда',0,.24),('уходят',.26,.57),('годы,',.62,.99),
                     ('но',1.38,1.58),('я',1.6,1.73),('вернусь',1.76,2.14)])
        self.assertEqual([r[2] for r in rows],['Куда уходят годы','но я вернусь'])
        self.assertTrue(all(a[1] <= b[0] for a,b in zip(rows,rows[1:])))

    def test_punctuation_inside_caption_remains(self):
        self.assertEqual(clean_caption('Раз, два, три,  '),'Раз, два, три')


if __name__=='__main__':unittest.main()
