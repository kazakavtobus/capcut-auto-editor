import * as THREE from 'three';
const host=document.getElementById('stage');
const source=document.createElement('canvas');
source.width=720;source.height=1280;
const ctx=source.getContext('2d');
let renderer=null,texture=null,scene=null,camera=null;
function draw(text){
  ctx.fillStyle='#24262c';ctx.fillRect(0,0,720,1280);
  ctx.strokeStyle='#ffffff35';ctx.lineWidth=2;ctx.setLineDash([10,12]);ctx.strokeRect(52,130,616,980);ctx.setLineDash([]);
  const rows=String(text).split(/\s+/).reduce((acc,word)=>{
    const last=acc[acc.length-1]||'';
    ctx.font='bold 48px Segoe UI, sans-serif';
    if(ctx.measureText(last+' '+word).width>570 && last)acc.push(word);
    else acc[acc.length-1]=(last+' '+word).trim();
    return acc;
  },['']);
  ctx.fillStyle='white';ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='bold 48px Segoe UI, sans-serif';
  rows.slice(0,6).forEach((line,i)=>ctx.fillText(line,360,640+(i-(Math.min(rows.length,6)-1)/2)*61,570));
  if(texture){texture.needsUpdate=true;renderer.render(scene,camera);}
}
try{
  renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
  renderer.setSize(202,360,false);
  renderer.domElement.style.height='100%';renderer.domElement.style.width='auto';
  scene=new THREE.Scene();scene.background=new THREE.Color('#101217');
  camera=new THREE.OrthographicCamera(-360,360,640,-640,0.1,10);camera.position.z=2;
  texture=new THREE.CanvasTexture(source);texture.colorSpace=THREE.SRGBColorSpace;
  scene.add(new THREE.Mesh(new THREE.PlaneGeometry(720,1280),new THREE.MeshBasicMaterial({map:texture})));
  host.appendChild(renderer.domElement);
}catch(e){renderer=null;texture=null;host.appendChild(source);}
window.setCaption=draw;draw('Слова песни');
