import React,{useEffect,useState} from 'react';
import {AbsoluteFill,Audio,Img,Composition,OffthreadVideo,Sequence,registerRoot,staticFile,useCurrentFrame,useVideoConfig,interpolate,delayRender,continueRender,cancelRender} from 'remotion';

const clip=(x)=>Math.max(0,Math.min(1,x));
const VideoLayer=({item,previousTransition})=>{
  const frame=useCurrentFrame();
  const incoming=previousTransition?Math.ceil(previousTransition/2):0;
  const outgoing=item.transition?Math.ceil(item.transition/2):0;
  const blur=12*Math.max(incoming?1-clip(frame/incoming):0,outgoing?clip((frame-item.frames+outgoing)/outgoing):0);
  return <AbsoluteFill style={{overflow:'hidden',backgroundColor:'#000'}}>
    <OffthreadVideo src={staticFile(item.file)} muted trimBefore={item.sourceFrame}
      style={{width:'100%',height:'100%',objectFit:'cover',filter:'blur('+blur+'px)',transform:'scale('+ (blur?1.035:1) +') scaleX('+(item.flip?-1:1)+')'}} />
  </AbsoluteFill>;
};
const Caption=({item,fontFamily,fontStyle,fontWeight})=>{
  const f=useCurrentFrame();
  const enter=Math.max(1,item.enter),exit=Math.max(1,item.exit);
  const scale=item.enter?interpolate(f,[0,enter],[0.82,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}):1;
  const opacity=item.exit?clip((item.frames-f)/exit):1;
  return <AbsoluteFill style={{display:'flex',alignItems:'center',justifyContent:'center',pointerEvents:'none'}}>
    {item.image?<Img src={staticFile(item.image)} style={{position:'relative',left:item.x,top:item.y,width:item.imageWidth,height:item.imageHeight,opacity,transform:'scale('+scale+')'}}/>:<div style={{position:'relative',left:item.x,top:item.y,maxWidth:'82%',whiteSpace:'pre-wrap',overflowWrap:'break-word',
      textAlign:'center',fontFamily,fontStyle,fontWeight,fontSynthesis:'none',fontSize:item.fontSize,lineHeight:1.12,color:item.color,
      textShadow:'3px 3px 0 rgba(0,0,0,0.65)',opacity,transform:'scale('+scale+')'}}>{item.text}</div>}
  </AbsoluteFill>;
};
// Compare actual Cyrillic pixels against an intentionally missing family.
const verifyRenderedFont=(family,style,weight)=>{
  const canvas=document.createElement('canvas');
  canvas.width=1500;canvas.height=120;
  const ctx=canvas.getContext('2d',{willReadFrequently:true});
  const sample='Съешь ещё этих мягких булок Aa09';
  const pixels=(name)=>{
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.font=style+' '+weight+' 60px "'+name+'", sans-serif';
    ctx.fillStyle='#fff';ctx.fillText(sample,8,80);
    return ctx.getImageData(0,0,canvas.width,canvas.height).data;
  };
  const actual=pixels(family),fallback=pixels('__StudioMissingFont__');
  if(!actual.some((value,i)=>value!==fallback[i])){
    throw Error('Caption font renders identically to system fallback: '+family);
  }
};
const Movie=({videos,captions,audio,font,fontFamily='StudioCaptionExact',fontStyle='normal',fontWeight=600})=>{
  const [handle]=useState(()=>delayRender('Loading exact local caption font'));
  useEffect(()=>{
    if(captions.length&&captions.every(c=>c.image)){continueRender(handle);return;}
    const face=new FontFace(fontFamily,'url("'+staticFile(font)+'")',{weight:String(fontWeight),style:fontStyle});
    const load=async()=>{
      await face.load();
      document.fonts.add(face);
      const descriptor=fontStyle+' '+fontWeight+' 69px "'+fontFamily+'"';
      const loaded=await document.fonts.load(descriptor,'АБВабвЁёABCabc012');
      await document.fonts.ready;
      if(face.status!=='loaded'||!loaded.includes(face)||!document.fonts.check(descriptor,'АБВабвЁёABCabc012')){
        throw Error('Exact caption font failed to load: '+fontFamily+' '+fontStyle+' '+fontWeight);
      }
      verifyRenderedFont(fontFamily,fontStyle,fontWeight);
      continueRender(handle);
    };
    load().catch(e=>cancelRender(e));
  },[font,fontFamily,fontStyle,fontWeight,handle]);
  return <AbsoluteFill style={{backgroundColor:'#000'}}>
    {videos.map((v,i)=><Sequence key={i} from={v.start} durationInFrames={v.frames}><VideoLayer item={v} previousTransition={i?videos[i-1].transition:0}/></Sequence>)}
    {captions.map((c,i)=><Sequence key={i} from={c.start} durationInFrames={c.frames}><Caption item={c} fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight}/></Sequence>)}
    <Sequence from={audio.start} durationInFrames={audio.frames}><Audio src={staticFile(audio.file)} trimBefore={audio.sourceFrame} volume={audio.volume}/></Sequence>
  </AbsoluteFill>;
};
const Root=()=> <Composition id="StudioMovie" component={Movie} width={1080} height={1920} fps={30} durationInFrames={30}
 defaultProps={{durationFrames:30,videos:[],captions:[],audio:{file:'audio.wav',start:0,frames:30,sourceFrame:0,volume:1},font:'caption.ttf'}}
 calculateMetadata={({props})=>({durationInFrames:props.durationFrames})}/>;
registerRoot(Root);
