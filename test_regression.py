from pathlib import Path
from caption_engine import obtain_captions,good_enough
from builder import cut_ends,MICRO

assert not good_enough([(20760000,22160000,'Анактриса')],22550000)
assert good_enough([(1000000,2300000,'она актриса'),(3200000,4900000,'несите оскар'),(5800000,7700000,'я ею пьяный')],10000000)
assert cut_ends([4266666,8016666,11316666],11000000,[])[-1]==11000000
print('Regression tests passed')
