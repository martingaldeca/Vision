############################################################################################
#
# The MIT License (MIT)
# 
# TASS Local Streamer
# Copyright (C) 2018 Adam Milton-Barker (AdamMiltonBarker.com)
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
# Title:         TASS Local Streamer
# Description:   Connects to the local server camera, processes and streams the modified stream.
# Configuration: required/confs.json
# Last Modified: 2018-09-09
#
# Example Usage:
#
#   $ python3.5 Local.py
#
############################################################################################

import os, sys, time, getopt, zmq, cv2, dlib, imutils, cv2, base64

import numpy              as np
import JumpWayMQTT.Device as JWDevice

from datetime          import datetime
from skimage.transform import resize
from imutils           import face_utils
from mvnc              import mvncapi as mvnc
from flask             import Flask, request, Response

from tools.Helpers     import Helpers
from tools.JumpWay     import JumpWay
from tools.OpenCV      import OpenCV
from tools.Facenet     import Facenet
from tools.MySql       import MySql

app = Flask(__name__)

class Streamer():
    
    def __init__(self):

        ###############################################################
        #
        # Sets up all default requirements and placeholders 
        #
        ###############################################################

        self.Helpers     = Helpers()
        self._confs      = self.Helpers.loadConfigs()
        self.LogFile     = self.Helpers.setLogFile(self._confs["aiCore"]["Logs"]+"/Local")  
        
        self.MySql       = MySql()
        
        self.OpenCV      = OpenCV()
        self.OCVframe    = None
        self.font        = cv2.FONT_HERSHEY_SIMPLEX
        self.fontColor   = (255,255,255)
        self.fontScale   = 1
        self.lineType    = 1
        self.identified  = 0

        self.Facenet     = Facenet()

        self.movidius, self.devices, self.device = self.Facenet.CheckDevices()
        self.fgraph,  self.fgraphfile            = self.Facenet.loadGraph("Facenet", self.movidius)

        self.validDir    = self._confs["Classifier"]["NetworkPath"] + self._confs["Classifier"]["ValidPath"]
        self.testingDir  = self._confs["Classifier"]["NetworkPath"] + self._confs["Classifier"]["TestingPath"]
        
        self.detector    = dlib.get_frontal_face_detector()
        self.predictor   = dlib.shape_predictor(self._confs["Classifier"]["Dlib"])

        self.connectToCamera()

        self.tassSocket  = None
        self.configureSocket()

        self.JumpWay    = JumpWay()
        self.JumpWayCL  = self.JumpWay.startMQTT()
        
        self.Helpers.logMessage(
			self.LogFile,
            "TASS",
            "INFO",
            "TASS Ready")
        
    def connectToCamera(self):

        ###############################################################
        #
        # Connects to the Foscam device using the configs in 
        # required/confs.json
        #
        ###############################################################
        
        self.OCVframe = cv2.VideoCapture(0)
        
        self.Helpers.logMessage(
            self.LogFile,
            "TASS",
            "INFO",
            "Connected To Camera")
        
    def configureSocket(self):

        ###############################################################
        #
        # Configures the socket we will stream the frames to
        #
        ###############################################################

        self.tassSocket = zmq.Context().socket(zmq.PUB)
        self.tassSocket.connect("tcp://"+self._confs["Socket"]["host"]+":"+str(self._confs["Socket"]["port"]))

        self.Helpers.logMessage(
                            self.LogFile,
                            "TASS",
                            "INFO",
                            "Connected To Socket: tcp://"+self._confs["Socket"]["host"]+":"+str(self._confs["Socket"]["port"]))
        
Streamer = Streamer()

while True:

    try:

        _, frame = Streamer.OCVframe.read()
        frame    = cv2.resize(frame, (640, 480)) 
        rawFrame = frame.copy()

        gray     = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        rects    = Streamer.detector(gray, 0)
            
        for (i, rect) in enumerate(rects):
            
            shape = face_utils.shape_to_np(
                Streamer.predictor(
                    gray,
                    rect))
            
            (x, y, w, h) = face_utils.rect_to_bb(rect)
            
            cv2.rectangle(
                frame, 
                (x, y), 
                (x + w, y + h), 
                (0, 255, 0), 
                2)
                
            for (x, y) in shape:
                
                cv2.circle(
                    frame, 
                    (x, y), 
                    1, 
                    (0, 255, 0), 
                    -1)
                    
            currentFace = rawFrame[
                max(0, rect.top()-100): min(rect.bottom()+100, 480),
                max(0, rect.left()-100): min(rect.right()+100, 640)]

            if currentFace is None:
                continue 
            
            for valid in os.listdir(Streamer.validDir):
                
                if valid.endswith('.jpg') or valid.endswith('.jpeg') or valid.endswith('.png') or valid.endswith('.gif'):
                    
                    inferStart = time.time()
                    
                    known, confidence = Streamer.Facenet.match(
                        Streamer.Facenet.infer(
                            cv2.imread(Streamer.validDir+valid), 
                            Streamer.fgraph),
                            Streamer.Facenet.infer(
                                cv2.flip(currentFace, 1), 
                                Streamer.fgraph))

                    user = valid.rsplit(".", 1)[0].title()
                    inferEnd = (inferStart - time.time())
                    
                    if (known==True):
                        
                        Streamer.identified = Streamer.identified + 1
                        theUSer = Streamer.MySql.getHuman(user)
                        print(theUSer)

                        Streamer.MySql.trackHuman(
                                                theUSer[0], 
                                                Streamer._confs["iotJumpWay"]["Location"], 
                                                0, 
                                                Streamer._confs["iotJumpWay"]["Zone"], 
                                                Streamer._confs["iotJumpWay"]["Device"])

                        Streamer.Helpers.logMessage(
                            Streamer.LogFile,
                            "TASS",
                            "INFO",
                            "TASS Identified " + user + " In " + str(inferEnd) + " Seconds With Confidence Of " + str(confidence))

                        Streamer.JumpWayCL.publishToDeviceChannel(
                            "TASS",
                            {
                                "WarningType":"SECURITY",
                                "WarningOrigin": Streamer._confs["Cameras"][0]["ID"],
                                "WarningValue": "RECOGNISED",
                                "WarningMessage": "RECOGNISED"
                            }
                        )

                        cv2.putText(
                            frame, 
                            user, 
                            (x,y), 
                            Streamer.font, 
                            Streamer.fontScale,
                            Streamer.fontColor,
                            Streamer.lineType)
                        break

                    else:
		
                        Streamer.Helpers.logMessage(
                            Streamer.LogFile,
                            "TASS",
                            "INFO",
                            "TASS Identified Unknown Human In " + str(inferEnd) + " Seconds With Confidence Of " + str(confidence))

                        Streamer.JumpWayCL.publishToDeviceChannel(
                            "TASS",
                            {
                                "WarningType": "SECURITY",
                                "WarningOrigin": Streamer._confs["Cameras"][0]["ID"],
                                "WarningValue": "INTRUDER",
                                "WarningMessage": "INTRUDER"
                            }
                        )

                        cv2.putText(
                            frame,
                            "Unknown " + str(confidence), 
                            (x,y), 
                            Streamer.font, 
                            Streamer.fontScale,
                            Streamer.fontColor,
                            Streamer.lineType)

                    cv2.imwrite("testProcessed.jpg", frame)
                    cv2.imwrite("testProcessedFull.jpg", currentFace)
 
        encoded, buffer = cv2.imencode('.jpg', frame)
        Streamer.tassSocket.send(base64.b64encode(buffer))

    except KeyboardInterrupt:
        Streamer.OCVframe.release()
        break