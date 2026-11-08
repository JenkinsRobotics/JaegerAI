import { fireEvent, render, screen } from '@testing-library/react';
import { act } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { VoiceDictation } from './VoiceDictation';

afterEach(()=>vi.unstubAllGlobals());
it('shows an explained unavailable microphone when recognition is unsupported',()=>{
 render(<VoiceDictation/>);
 expect(screen.getByRole('button',{name:'Dictation unavailable in this browser'})).toBeDisabled();
});
it('dictates into the draft without sending and stops the owned recognizer on cleanup',async()=>{
 let recognition: any;
 class Recognition {
  start=vi.fn(); stop=vi.fn(); onresult?: (event:unknown)=>void;
  constructor(){recognition=this;}
 }
 vi.stubGlobal('webkitSpeechRecognition',Recognition);
 const send=vi.fn();
 const {unmount}=render(<form onSubmit={send}><textarea className="jg-composer__input" aria-label="Draft" defaultValue="Keep this"/><VoiceDictation/></form>);
 fireEvent.click(screen.getByRole('button',{name:'Dictate message'}));
 expect(recognition.start).toHaveBeenCalledOnce();
 const result=Object.assign([{transcript:'and add this'}],{isFinal:true});
 await act(async()=>recognition.onresult({resultIndex:0,results:[result]}));
 expect(screen.getByRole('textbox',{name:'Draft'})).toHaveValue('Keep this and add this');
 expect(screen.getByRole('button',{name:'Stop dictation'})).toBeTruthy();
 expect(send).not.toHaveBeenCalled();
 unmount();expect(recognition.stop).toHaveBeenCalledOnce();
});
