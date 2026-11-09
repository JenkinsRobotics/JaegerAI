import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { ToolActivity } from './ToolActivity';

it('shows retained file output on expansion and retains the actual input', () => {
 render(<ToolActivity part={{kind:'toolInvocation',callId:'read',toolName:'read_file',input:{path:'README.md'},state:'completed',output:'Recorded file contents'}}/>);
 fireEvent.click(screen.getByRole('button',{name:/Read README.md/}));
 expect(screen.getByText('Recorded file contents')).toBeTruthy();
 expect(screen.getByText('Input')).toBeTruthy();
});
it('labels an unconfirmed command outcome explicitly', () => {
 render(<ToolActivity part={{kind:'toolInvocation',callId:'shell',toolName:'run_shell',input:{command:'pwd'},state:'unknown'}}/>);
 expect(screen.getByText('Outcome unknown for')).toBeTruthy();
 expect(screen.queryByText('Completed')).toBeNull();
});
