import {afterEach, expect, it, vi} from 'vitest';
import {detectDisplayMode, watchDisplayMode} from './host';

afterEach(() => {vi.unstubAllGlobals(); delete document.documentElement.dataset.jaegerDisplayMode;});

it('detects Safari Home Screen mode independently of the native macOS host', () => {
 vi.stubGlobal('navigator', {standalone:true});
 expect(detectDisplayMode()).toBe('standalone');
 vi.stubGlobal('navigator', {standalone:false});
 vi.stubGlobal('matchMedia', () => ({matches:false}));
 expect(detectDisplayMode()).toBe('browser');
});

it('tracks the standard installed display mode and removes its listener', () => {
 const media=Object.assign(new EventTarget(), {matches:false});
 const remove=vi.spyOn(media,'removeEventListener');
 vi.stubGlobal('matchMedia', () => media);
 const stop=watchDisplayMode();
 expect(document.documentElement.dataset.jaegerDisplayMode).toBe('browser');
 media.matches=true; media.dispatchEvent(new Event('change'));
 expect(document.documentElement.dataset.jaegerDisplayMode).toBe('standalone');
 stop(); expect(remove).toHaveBeenCalledWith('change',expect.any(Function));
});
