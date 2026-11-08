/** Production shell integration with real Settings/AppWindow components.
 * API and layout are synthetic; this is not browser or backend acceptance. */
import { afterEach, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MockSource } from '../api/mock';
import { StableDemo } from './StableDemo';

afterEach(() => { localStorage.clear(); history.replaceState(null, '', '/'); });

it('renders and operates existing appearance controls from the production gear', async () => {
 render(<StableDemo source={new MockSource()} />);
 fireEvent.click(screen.getByRole('button', {name:'Settings'}));
 expect(location.pathname).toBe('/settings/appearance');
 const light = await screen.findByRole('radio', {name:'Light'}, {timeout:8000});
 fireEvent.click(light);
 expect(light).toHaveAttribute('aria-checked', 'true');
 expect(document.documentElement).toHaveClass('aether-light-theme');
 expect(screen.getAllByRole('navigation', {name:'Jaeger navigation'})).toHaveLength(1);
 expect(screen.queryByText('Settings for this section will be added here.')).toBeNull();
});

it('renders direct settings links and follows browser navigation back to chat', async () => {
 history.replaceState(null, '', '/settings/appearance');
 render(<StableDemo source={new MockSource()} />);
 await screen.findByRole('radio', {name:'System'}, {timeout:8000});
 history.replaceState(null, '', '/');
 fireEvent(window, new PopStateEvent('popstate'));
 await waitFor(() => expect(screen.queryByRole('radio', {name:'System'})).toBeNull());
 expect(screen.getByRole('region', {name:'Chat'})).toBeVisible();
});

it('opens and dismisses the command palette inside embedded Settings', async () => {
 history.replaceState(null, '', '/settings/appearance');
 render(<StableDemo source={new MockSource()} />);
 await screen.findByRole('radio', {name:'System'}, {timeout:8000});
 fireEvent.keyDown(window, {key:'k',ctrlKey:true});
 expect(screen.getByRole('dialog', {name:'Search'})).toBeVisible();
 fireEvent.keyDown(screen.getByRole('combobox', {name:'Search'}), {key:'Escape'});
 await waitFor(() => expect(screen.queryByRole('dialog', {name:'Search'})).toBeNull());
});
