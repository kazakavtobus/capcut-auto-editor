const fs=require('node:fs');
const path=require('node:path');
const {bundle}=require('@remotion/bundler');
const {selectComposition,renderMedia}=require('@remotion/renderer');
(async()=>{
  const [manifest,publicDir,output]=process.argv.slice(2);
  if(!manifest||!publicDir||!output)throw Error('Expected manifest, media directory and output.');
  const inputProps=JSON.parse(fs.readFileSync(manifest,'utf8'));
  const serveUrl=await bundle({entryPoint:path.join(__dirname,'index.jsx'),publicDir:path.resolve(publicDir)});
  try{
    const composition=await selectComposition({serveUrl,id:'StudioMovie',inputProps});
    const options={composition,serveUrl,inputProps,codec:'h264',audioCodec:'aac',outputLocation:path.resolve(output),
      concurrency:2,hardwareAcceleration:'if-possible',videoBitrate:'10M',audioBitrate:'192k',pixelFormat:'yuv420p'};
    let last=-1;
    await renderMedia({...options,onProgress:({progress})=>{
      const pct=Math.floor(progress*100);
      if(pct!==last){last=pct;process.stdout.write('PROGRESS '+pct+'\n');}
    }});
  }finally{fs.rmSync(serveUrl,{recursive:true,force:true});}
})().catch(err=>{console.error(err);process.exitCode=1;});
