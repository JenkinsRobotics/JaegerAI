"""Classify background audio locally with macOS Sound Analysis."""
from Foundation import NSObject, NSURL
import objc
import SoundAnalysis as SA


class JaegerSoundObserver(NSObject, protocols=[objc.protocolNamed("SNResultsObserving")]):
    def request_didProduceResult_(self, request, result):
        for item in result.classifications()[:5]:
            label = str(item.identifier()).lower()
            if item.confidence() >= 0.55 and ("music" in label or label in {"singing", "television"}):
                self.background = label


def background_label(wav):
    observer = JaegerSoundObserver.alloc().init()
    observer.background = ""
    analyzer, error = SA.SNAudioFileAnalyzer.alloc().initWithURL_error_(NSURL.fileURLWithPath_(str(wav)), None)
    if error:
        raise RuntimeError("Local sound classification could not read this clip.")
    request, error = SA.SNClassifySoundRequest.alloc().initWithClassifierIdentifier_error_(SA.SNClassifierIdentifierVersion1, None)
    if error:
        raise RuntimeError("Local sound classifier unavailable.")
    ok, error = analyzer.addRequest_withObserver_error_(request, observer, None)
    if not ok:
        raise RuntimeError("Local sound classification unavailable.")
    analyzer.analyze()
    return observer.background
