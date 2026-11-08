import {fireEvent,render,screen} from '@testing-library/react';
import {expect,it} from 'vitest';
import {ActivityFold} from './MinimalChat';
import {STREAM_STYLES} from './streamStyle';
import type {ChatPart} from './host';

it('keeps intermediate commentary readable on demand and collapses when work finishes',()=>{
 const parts:ChatPart[]=[{kind:'markdownContent',text:'Checking the install path'},
  {kind:'progress',message:'Inspecting'},
  {kind:'toolInvocation',callId:'c',toolName:'read_file',input:{path:'package.json'},state:'executing'}];
 const props={parts,links:{onCopy:()=>{},onOpen:()=>{}},style:STREAM_STYLES.instant};
 const {rerender}=render(<ActivityFold {...props} live/>);
 expect(screen.queryByText('Checking the install path')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:/Show activity/}));
 expect(screen.getByText('Checking the install path')).toBeTruthy();
 expect(screen.getByText('package.json')).toBeTruthy();
 expect(screen.getByText('Inspecting')).toBeTruthy();
 rerender(<ActivityFold {...props} live={false}/>);
 expect(screen.queryByText('Checking the install path')).toBeNull();
 expect(screen.getByRole('button',{name:/Show activity/}).getAttribute('aria-expanded')).toBe('false');
});
