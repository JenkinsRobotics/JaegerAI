import { useEffect, useState } from 'react';
export interface AudioPreferences { inputId:string; outputId:string }
const KEY='jaeger.audio.preferences.v1', EVENT='jaeger:audio-preferences';
export function readAudioPreferences():AudioPreferences{
 try{const raw=JSON.parse(localStorage.getItem(KEY)||'null');if(raw && typeof raw.inputId==='string' && typeof raw.outputId==='string' && raw.inputId.length<=512 && raw.outputId.length<=512)return {inputId:raw.inputId,outputId:raw.outputId};}catch{}
 return {inputId:'',outputId:''};
}
export function saveAudioPreferences(value:AudioPreferences){
 if(typeof value.inputId!=='string' || typeof value.outputId!=='string' || value.inputId.length>512 || value.outputId.length>512)throw Error('Invalid audio device selection');
 localStorage.setItem(KEY,JSON.stringify({inputId:value.inputId,outputId:value.outputId}));window.dispatchEvent(new Event(EVENT));
}
export function useAudioPreferences(){
 const [value,setValue]=useState(readAudioPreferences);
 useEffect(()=>{const sync=()=>setValue(readAudioPreferences());const storage=(e:StorageEvent)=>{if(e.key===KEY || e.key===null)sync();};window.addEventListener(EVENT,sync);window.addEventListener('storage',storage);return()=>{window.removeEventListener(EVENT,sync);window.removeEventListener('storage',storage);};},[]);
 return [value,saveAudioPreferences] as const;
}
