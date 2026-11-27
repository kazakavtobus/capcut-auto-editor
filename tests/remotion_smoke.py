"""Real headless renderer smoke test; no private fonts, LUTs, music or video."""
import json, os, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
work=ROOT/'remotion-smoke';work.mkdir(exist_ok=True)
public=work/'public';public.mkdir(exist_ok=True)
def run(*args):
    subprocess.run(list(map(str,args)),check=True)
font=Path(os.environ['WINDIR'])/'Fonts'/'timesbi.ttf'
shutil.copy2(font,public/'caption.ttf')
run('ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=360x640:rate=30:duration=1',
    '-an','-c:v','libx264','-pix_fmt','yuv420p',public/'clip.mp4')
run('ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','sine=frequency=440:duration=1',
    '-c:a','pcm_s16le',public/'audio.wav')
plan=dict(durationFrames=30,font='caption.ttf',fontFamily='StudioCaptionExactSmoke',fontStyle='italic',fontWeight=700,
    videos=[dict(file='clip.mp4',start=0,frames=15,sourceFrame=0,transition=6),
            dict(file='clip.mp4',start=15,frames=15,sourceFrame=15,transition=0)],
    captions=[dict(start=0,frames=30,text='Тест Remotion',fontSize=69,color='#ffffff',x=0,y=0,enter=5,exit=6)],
    audio=dict(file='audio.wav',start=0,frames=30,sourceFrame=0,volume=1))
manifest=work/'manifest.json';manifest.write_text(json.dumps(plan,ensure_ascii=False),encoding='utf-8')
output=work/'output.mp4'
runtime=os.environ.get('STUDIO_SMOKE_RUNTIME')
if runtime:
    runtime=Path(runtime)
    run(runtime/'node.exe',runtime/'render.cjs',manifest,public,output,'cpu','',runtime/'browser'/'chrome-headless-shell.exe')
else:
    run('node',ROOT/'assets'/'remotion'/'render.cjs',manifest,public,output,'cpu')
info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]))
v=next(x for x in info['streams'] if x['codec_type']=='video')
a=next(x for x in info['streams'] if x['codec_type']=='audio')
assert (v['width'],v['height'],v['avg_frame_rate'])==(1080,1920,'30/1'),v
assert a['codec_name']=='aac',a
assert abs(float(info['format']['duration'])-1)<.15,info['format']
print('Remotion output validated:',output)
