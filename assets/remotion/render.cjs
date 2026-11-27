const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const {bundle}=require('@remotion/bundler');
const {selectComposition,renderMedia}=require('@remotion/renderer');
function canUseNvenc(ffmpeg,mode){
  if(mode!=='auto'||!ffmpeg)return false;
  const probe=spawnSync(ffmpeg,['-hide_banner','-loglevel','error','-nostdin','-f','lavfi','-i','color=black:s=1080x1920:r=30','-frames:v','2','-an','-pix_fmt','yuv420p','-c:v','h264_nvenc','-f','null','-'],{windowsHide:true,timeout:20000,encoding:'utf8'});
  if(probe.status===0&&!probe.error)return true;
  process.stdout.write('ENCODER_PROBE: NVENC unavailable; using CPU\n');
  return false;
}
(async()=>{
  const [manifest,publicDir,output,mode='cpu',ffmpeg,browserExecutable]=process.argv.slice(2);
  if(!manifest||!publicDir||!output||!['cpu','auto'].includes(mode))throw Error('Expected manifest, media directory, output and optional cpu/auto mode.');
  const inputProps=JSON.parse(fs.readFileSync(manifest,'utf8'));
  const gpu=canUseNvenc(ffmpeg,mode);
  console.log('STAGE: Подготовка композиции Remotion');
  const serveUrl=await bundle({entryPoint:path.join(__dirname,'index.jsx'),publicDir:path.resolve(publicDir)});
  try{
    console.log('STAGE: Запуск Chromium и загрузка композиции');
    const composition=await selectComposition({serveUrl,id:'StudioMovie',inputProps,browserExecutable});
    const options={composition,serveUrl,inputProps,browserExecutable,codec:'h264',audioCodec:'aac',outputLocation:path.resolve(output),
      concurrency:mode==='cpu'?2:Math.max(2,Math.min(4,Math.floor(os.availableParallelism()/3))),videoBitrate:'10M',audioBitrate:'192k',pixelFormat:'yuv420p'};
    console.log('STAGE: Потоков рендера: '+options.concurrency);
    async function render(useGpu){
      let last=-1;
      process.stdout.write('ENCODER: '+(useGpu?'NVENC requested':'CPU')+'\n');
      await renderMedia({...options,hardwareAcceleration:useGpu?'if-possible':'disable',onProgress:({progress})=>{
        const pct=Math.floor(progress*100);
        if(pct!==last){last=pct;process.stdout.write('PROGRESS '+pct+'\n');}
      }});
    }
    try{await render(gpu);}
    catch(err){
      if(!gpu)throw err;
      // A successful probe of system FFmpeg does not guarantee Remotion's own
      // FFmpeg can initialize the encoder. Retry once, explicitly on CPU.
      console.warn('GPU render failed; retrying once on CPU:',String(err).slice(-2000));
      fs.rmSync(path.resolve(output),{force:true});
      await render(false);
    }
  }finally{fs.rmSync(serveUrl,{recursive:true,force:true});}
})().catch(err=>{console.error(err);process.exitCode=1;});
