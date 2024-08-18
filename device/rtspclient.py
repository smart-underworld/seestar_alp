""" OpenCV Backend RTSP Client """

# Adapted from https://github.com/dactylroot/rtsp/tree/master

import cv2
from io import BytesIO
from PIL import Image

from threading import Thread

class RtspClient:
    """ Maintain live RTSP feed without buffering. """
    _stream = None

    def __init__(self, rtsp_server_uri, verbose = False):
        """
            rtsp_server_uri: the path to an RTSP server. should start with "rtsp://"
            verbose: print log or not
        """
        self.rtsp_server_uri = rtsp_server_uri
        self._verbose = verbose

        self._bg_run = False
        self.open()

    def __enter__(self,*args,**kwargs):
        """ Returns the object which later will have __exit__ called.
            This relationship creates a context manager. """
        return self

    def __exit__(self, type=None, value=None, traceback=None):
        """ Together with __enter__, allows support for `with-` clauses. """
        self.close()

    def open(self):
        if self.isOpened():
            return
        self._stream = cv2.VideoCapture(self.rtsp_server_uri)
        if self._verbose:
            print("Connected to video source {}.".format(self.rtsp_server_uri))
        self._bg_run = True
        t = Thread(target=self._update, args=())
        t.daemon = True
        t.start()
        self._bgt = t
        return self

    def close(self):
        """ signal background thread to stop. release CV stream """
        self._bg_run = False
        self._bgt.join()
        if self._verbose:
            print("Disconnected from {}".format(self.rtsp_server_uri))

    def isOpened(self):
        """ return true if stream is opened and being read, else ensure closed """
        try:
            return (self._stream is not None) and self._stream.isOpened() and self._bg_run
        except:
            self.close()
            return False

    def _update(self):
        while self.isOpened():
            #print("rtsp update loop")
            (grabbed, frame) = self._stream.read()
            if not grabbed:
                self._bg_run = False
            else:
                self._queue = frame
            #print("rtsp grabbed", grabbed)
        self._stream.release()

    def read(self,raw=False):
        """ Retrieve most recent frame and convert to PIL. Return unconverted with raw=True. """
        try:
            if raw:
                return self._queue
            else:
                return Image.fromarray(cv2.cvtColor(self._queue, cv2.COLOR_BGR2RGB))
        except:
            return None

# def preview(self):
#     """ Blocking function. Opens OpenCV window to display stream. """
#     win_name = 'RTSP'
#     cv2.namedWindow(win_name, cv2.WINDOW_AUTOSIZE)
#     cv2.moveWindow(win_name,20,20)
#     while(self.isOpened()):
#         cv2.imshow(win_name,self.read(raw=True))
#         if cv2.waitKey(30) == ord('q'): # wait 30 ms for 'q' input
#             break
#     cv2.waitKey(1)
#     cv2.destroyAllWindows()
#     cv2.waitKey(1)
