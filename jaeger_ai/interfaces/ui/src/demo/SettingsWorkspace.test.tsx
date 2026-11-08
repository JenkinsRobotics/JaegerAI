import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import * as voice from '../chat/voiceIO';
import {readAudioPreferences} from '../settings/audioPreferences';
import {SettingsWorkspace} from './SettingsWorkspace';
afterEach(()=>{cleanup();localStorage.clear();vi.restoreAllMocks();});
it('opens working audio controls through the Settings button Voice navigation',async()=>{
 const capability=vi.fn(async()=>({transcription:true,speech:true}));
 vi.spyOn(voice,'createVoiceIO').mockReturnValue({capability,devices:async()=>({microphones:[],speakers:[{deviceId:'studio',label:'Studio speakers'}]}),capture:async()=>'',speak:async()=>{}});
 render(<SettingsWorkspace onClose={()=>{}}/>);fireEvent.click(screen.getByRole('button',{name:'Voice'}));await act(async()=>{});
 expect(capability).toHaveBeenCalledTimes(1);expect(screen.queryByText('Settings for this section will be added here.')).toBeNull();
 fireEvent.change(screen.getByRole('combobox',{name:'Voice speaker'}),{target:{value:'studio'}});expect(readAudioPreferences().outputId).toBe('studio');expect(screen.getByText('Speech services available')).toBeTruthy();
});
