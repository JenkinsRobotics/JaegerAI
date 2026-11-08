import { nativeBridge } from '../platform/native';
import { NativeVoiceIO } from './nativeVoiceIO';
import { BrowserVoiceIO, type VoiceIO } from './webSpeech';
/** One platform adapter selection shared by chat and settings. */
export function createVoiceIO():VoiceIO{return nativeBridge()?new NativeVoiceIO():new BrowserVoiceIO();}
