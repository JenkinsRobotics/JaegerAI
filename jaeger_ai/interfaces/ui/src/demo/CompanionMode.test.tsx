import {fireEvent,render,screen} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {CompanionMode} from './CompanionMode';
it('switches modes with descriptions and closes after selection',()=>{
 const onChange=vi.fn();
 render(<CompanionMode team={false} onChange={onChange}/>);
 fireEvent.click(screen.getByRole('button',{name:'Switch companion mode'}));
 fireEvent.click(screen.getByRole('button',{name:/Team Check in/}));
 expect(onChange).toHaveBeenCalledWith(true);
 expect(screen.queryByRole('group')).toBeNull();
});
it('Escape dismisses the picker without closing its enclosing sidebar',()=>{
 const escape=vi.fn();
 document.addEventListener('keydown',escape);
 render(<CompanionMode team onChange={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'Switch companion mode'}));
 fireEvent.keyDown(document,{key:'Escape'});
 expect(screen.queryByRole('group')).toBeNull();
 expect(escape).not.toHaveBeenCalled();
 document.removeEventListener('keydown',escape);
});
