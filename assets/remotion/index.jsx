import React,{useEffect,useState} from 'react';
import {AbsoluteFill,Audio,Composition,OffthreadVideo,Sequence,registerRoot,staticFile,useCurrentFrame,useVideoConfig,interpolate,delayRender,continueRender,cancelRender} from 'remotion';

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
const Caption=({item})=>{
  const f=useCurrentFrame();
  const enter=Math.max(1,item.enter),exit=Math.max(1,item.exit);
  const scale=item.enter?interpolate(f,[0,enter],[0.82,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}):1;
  const opacity=item.exit?clip((item.frames-f)/exit):1;
  return <AbsoluteFill style={{display:'flex',alignItems:'center',justifyContent:'center',pointerEvents:'none'}}>
    <div style={{position:'relative',left:item.x,top:item.y,maxWidth:'82%',whiteSpace:'pre-wrap',overflowWrap:'break-word',
      textAlign:'center',fontFamily:'StudioCaption',fontSize:item.fontSize,lineHeight:1.12,fontWeight:600,color:item.color,
      textShadow:'3px 3px 0 rgba(0,0,0,0.65)',opacity,transform:'scale('+scale+')'}}>{item.text}</div>
  </AbsoluteFill>;
};
const Movie=({videos,captions,audio,font})=>{
  const [handle]=useState(()=>delayRender('Loading exact local caption font'));
  useEffect(()=>{
    const face=new FontFace('StudioCaption','url("'+staticFile(font)+'")',{weight:'600'});
    face.load().then(f=>{document.fonts.add(f);continueRender(handle);}).catch(e=>cancelRender(e));
  },[font,handle]);
  return <AbsoluteFill style={{backgroundColor:'#000'}}>
    {videos.map((v,i)=><Sequence key={i} from={v.start} durationInFrames={v.frames}><VideoLayer item={v} previousTransition={i?videos[i-1].transition:0}/></Sequence>)}
    {captions.map((c,i)=><Sequence key={i} from={c.start} durationInFrames={c.frames}><Caption item={c}/></Sequence>)}
    <Sequence from={audio.start} durationInFrames={audio.frames}><Audio src={staticFile(audio.file)} trimBefore={audio.sourceFrame} volume={audio.volume}/></Sequence>
  </AbsoluteFill>;
};
const Root=()=> <Composition id="StudioMovie" component={Movie} width={1080} height={1920} fps={30} durationInFrames={30}
 defaultProps={{durationFrames:30,videos:[],captions:[],audio:{file:'audio.wav',start:0,frames:30,sourceFrame:0,volume:1},font:'caption.ttf'}}
 calculateMetadata={({props})=>({durationInFrames:props.durationFrames})}/>;
registerRoot(Root);
