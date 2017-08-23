#!/bin/env python
"""
Script to set trimdac values on a chamber
By: Christine McLean (ch.mclean@cern.ch),
    Cameron Bravo (c.bravo@cern.ch),
    Elizabeth Starling (elizabeth.starling@cern.ch),
    Louis Moureaux (lmoureau@ulb.ac.be),
"""

import sys
import numpy as np
import ROOT as r
from array import array
from gempython.tools.vfat_user_functions_uhal import *
from gempython.utils.nesteddict import nesteddict as ndict
from gempython.utils.wrappers import runCommand, envCheck
from mapping.chamberInfo import chamber_config

from qcoptions import parser

# To be moved in anautilities.py later on
def medianAndMAD(arrayData, axis=0):
    """Returns a tuple containing the (median, MAD) of a data sample"""
    median = np.median(arrayData, axis)
    # Build an array of the same dimensions as median by repeating it
    repeatedMedian = np.expand_dims(median, axis=axis).repeat(arrayData.shape[axis], axis=axis)
    diff = np.abs(arrayData - repeatedMedian)
    return median, np.median(diff, axis)

parser.add_option("--trimRange", type="string", dest="rangeFile", default=None,
                  help="Specify the file to take trim ranges from", metavar="rangeFile")
parser.add_option("--dirPath", type="string", dest="dirPath", default=None,
                  help="Specify the path where the scan data should be stored", metavar="dirPath")
parser.add_option("--zscore", type="float", dest="zscore",
                  help="Z-score for choosing VT1", metavar="zscore", default=5)
parser.add_option("--vt1bump", type="int", dest="vt1bump",
                  help="Adds a constant term to the computed VT1", metavar="vt1bump", default=0)
parser.add_option("--vt1", type="int", dest="vt1",
                  help="Initial VThreshold1 DAC value for all VFATs", metavar="vt1", default=100)

uhal.setLogLevelTo( uhal.LogLevel.WARNING )
(options, args) = parser.parse_args()

rangeFile = options.rangeFile
ztrim = options.ztrim
print 'trimming at z = %f'%ztrim

envCheck('DATA_PATH')
envCheck('BUILD_HOME')

dataPath = os.getenv('DATA_PATH')

from fitting.fitScanData import fitScanData
import subprocess,datetime
startTime = datetime.datetime.now().strftime("%Y.%m.%d.%H.%M")
print startTime

ohboard = getOHObject(options.slot,options.gtx,options.shelf,options.debug)

if options.dirPath == None: dirPath = '%s/%s/trimming/z%f/%s'%(dataPath,chamber_config[options.gtx],ztrim,startTime)
else: dirPath = options.dirPath

def runSCurve(filename, doFit=True):
    """Runs an S-curve with the current VFAT configuration. The data file will
    be written to <dirPath>/<filename>. If doFit is True (the default), the data
    is also fitted, and the fit results are returned."""
    filename = "%s/%s"%(dirPath,filename)
    runCommand(["ultraScurve.py",
                "--shelf=%i"%(options.shelf),
                "-s%d"%(options.slot),
                "-g%d"%(options.gtx),
                "--filename=%s"%(filename),
                "--vfatmask=%i"%(options.vfatmask),
                "--nevts=%i"%(options.nevts)]
            )
    if doFit:
        return fitScanData(filename)

# bias vfats
biasAllVFATs(ohboard,options.gtx,0x0,enable=False)
writeAllVFATs(ohboard, options.gtx, "VThreshold1", options.vt1, 0)

CHAN_MIN = 0
CHAN_MAX = 128
VT1_MAX = 255

masks = ndict()
for vfat in range(0,24):
    for ch in range(CHAN_MIN,CHAN_MAX):
        masks[vfat][ch] = False

#Find trimRange for each VFAT
tRanges    = ndict()
tRangeGood = ndict()
trimVcal = ndict()
trimCH   = ndict()
goodSup  = ndict()
goodInf  = ndict()
for vfat in range(0,24):
    tRanges[vfat] = 0
    tRangeGood[vfat] = False
    trimVcal[vfat] = 0
    trimCH[vfat] = 0
    goodSup[vfat] = -99
    goodInf[vfat] = -99

###############
# TRIMDAC = 0
###############
# Configure for initial scan
for vfat in range(0,24):
    writeVFAT(ohboard, options.gtx, vfat, "ContReg3", tRanges[vfat],0)

zeroAllVFATChannels(ohboard,options.gtx,mask=0x0)

# Scurve scan with trimdac set to 0
muFits_0 = runSCurve("SCurveData_trimdac0_range0.root")
for vfat in range(0,24):
    for ch in range(CHAN_MIN,CHAN_MAX):
        if muFits_0[4][vfat][ch] < 0.1: masks[vfat][ch] = True

#calculate the sup and set trimVcal
sup = ndict()
supCH = ndict()
for vfat in range(0,24):
    if(tRangeGood[vfat]): continue
    sup[vfat] = 999.0
    supCH[vfat] = -1
    for ch in range(CHAN_MIN,CHAN_MAX):
        if(masks[vfat][ch]): continue
        if(muFits_0[0][vfat][ch] - ztrim*muFits_0[1][vfat][ch] < sup[vfat] and muFits_0[0][vfat][ch] - ztrim*muFits_0[1][vfat][ch] > 0.1): 
            sup[vfat] = muFits_0[0][vfat][ch] - ztrim*muFits_0[1][vfat][ch]
            supCH[vfat] = ch
    goodSup[vfat] = sup[vfat]
    trimVcal[vfat] = sup[vfat]
    trimCH[vfat] = supCH[vfat]
    

if rangeFile == None:
    #This loop determines the trimRangeDAC for each VFAT
    for trimRange in range(0,5):
        #Set Trim Ranges
        for vfat in range(0,24):
            writeVFAT(ohboard, options.gtx, vfat, "ContReg3", tRanges[vfat],0)
        ###############
        # TRIMDAC = 31
        ###############
        #Setting trimdac value
        for vfat in range(0,24):
            for scCH in range(CHAN_MIN,CHAN_MAX):
                writeVFAT(ohboard,options.gtx,vfat,"VFATChannels.ChanReg%d"%(scCH),31)
        
        #Scurve scan with trimdac set to 31 (maximum trimming)
        #For each channel, check that the infimum of the scan with trimDAC = 31 is less than the subprimum of the scan with trimDAC = 0. The difference should be greater than the trimdac range.
        muFits_31 = runSCurve("SCurveData_trimdac31_range%i.root"%trimRange)
        
        inf = ndict()
        infCH = ndict()
        #Check to see if the new trimRange is good
        for vfat in range(0,24):
            if(tRangeGood[vfat]): continue
            sup[vfat] = 999.0
            inf[vfat] = 0.0
            supCH[vfat] = -1
            infCH[vfat] = -1
            for ch in range(CHAN_MIN,CHAN_MAX):
                if(masks[vfat][ch]): continue
                if(muFits_31[0][vfat][ch] - ztrim*muFits_31[1][vfat][ch] > inf[vfat]): 
                    inf[vfat] = muFits_31[0][vfat][ch] - ztrim*muFits_31[1][vfat][ch]
                    infCH[vfat] = ch
                if(muFits_0[0][vfat][ch] - ztrim*muFits_0[1][vfat][ch] < sup[vfat] and muFits_0[0][vfat][ch] - ztrim*muFits_0[1][vfat][ch] > 0.1): 
                    sup[vfat] = muFits_0[0][vfat][ch] - ztrim*muFits_0[1][vfat][ch]
                    supCH[vfat] = ch
            print "vfat: %i"%vfat
            print muFits_0[0][vfat]
            print muFits_31[0][vfat]
            print "sup: %f  inf: %f"%(sup[vfat],inf[vfat])
            print "supCH: %f  infCH: %f"%(supCH[vfat],infCH[vfat])
            print " "
            if(inf[vfat] <= sup[vfat]):
                tRangeGood[vfat] = True
                goodSup[vfat] = sup[vfat]
                goodInf[vfat] = inf[vfat]
                trimVcal[vfat] = sup[vfat]
                trimCH[vfat] = supCH[vfat]
            else:
                tRanges[vfat] += 1
                trimVcal[vfat] = sup[vfat]
                trimCH[vfat] = supCH[vfat]
    ##############################
    # Threshold scan @ TrimDAC=31
    ##############################
    print "Starting threshold scan"
    runCommand(["ultraThreshold.py","--shelf=%i"%(options.shelf),"-s%d"%(options.slot),"-g%d"%(options.gtx),"--vfatmask=%i"%(options.vfatmask),"--perchannel"])
    thrFile = r.TFile("VThreshold1Data_Trimmed.root")
    noiseMax = np.zeros((24, 128), dtype=int)
    for event in thrFile.thrTree:
        if event.Nhits > 0:
            noiseMax[event.vfatN][event.vfatCH] = max(noiseMax[event.vfatN][event.vfatCH], event.vth1)
            pass
        pass
    noiseMaxMedian, noiseMaxMAD = medianAndMAD(noiseMax, axis=1)
    vt1 = (noiseMaxMedian + options.zscore * noiseMaxMAD + options.vt1bump).astype(int)
    # Bias VFATs
    biasAllVFATs(ohboard,options.gtx,0x0,enable=False)
    print "Configuring VT1"
    for vfat in range(24):
        print "VFAT %d: VT1=%d"%(vfat, vt1[vfat])
        writeVFAT(ohboard, options.gtx, vfat, "VThreshold1", vt1[vfat], 0)
        pass
    ###############
    # TRIMDAC = 0
    ###############
    # Configure
    print "Configuring TrimRange"
    zeroAllVFATChannels(ohboard,options.gtx,mask=0x0)
    for vfat in range(0,24):
        writeVFAT(ohboard, options.gtx, vfat, "ContReg3", tRanges[vfat],0)
    # Scurve scan with trimdac set to 0
    muFits_0 = runSCurve("SCurveData_trimdac0_range0_vt1.root")
    for vfat in range(0,24):
        trimValue = muFits_0[0][vfat] - ztrim*muFits_0[1][vfat]
        supCH[vfat] = np.argmin(trimValue)
        goodSup[vfat] = trimValue[supCH[vfat]]
        print "vfat: %i"%vfat
        print "sup:   %f"%goodSup[vfat]
        print "supCH: %f"%supCH[vfat]
    print "trimRanges found"
else:
    try:
        rF = TFile(rangeFile)
        for event in rF.scurveTree:
            if event.vcal == 10:
                if event.vfatCH == 10:
                    writeVFAT(ohboard, options.gtx, int(event.vfatN), "ContReg3", int(event.trimRange),0)
                    tRanges[event.vfatN] = event.trimRange
                pass
            pass
        pass
    except Exception as e:
        print "%s could not be loaded\n"%rangeFile
        print e
        exit(404)

#Init trimDACs to all zeros
trimDACs = ndict()
for vfat in range(0,24):
    for ch in range(CHAN_MIN,CHAN_MAX):
        trimDACs[vfat][ch] = 0

# This is a binary search to set each channel's trimDAC
for i in range(0,5):
    # First write this steps values to the VFATs
    for vfat in range(0,24):
        for ch in range(CHAN_MIN,CHAN_MAX):
            trimDACs[vfat][ch] += pow(2,4-i)
            writeVFAT(ohboard,options.gtx,vfat,"VFATChannels.ChanReg%d"%(ch),trimDACs[vfat][ch])
    # Run an SCurve and fit data
    fitData = runSCurve("SCurveData_binarySearch%i.root"%i)
    # Now use data to determine the new trimDAC value
    for vfat in range(0,24):
        for ch in range(CHAN_MIN,CHAN_MAX):
            if(fitData[0][vfat][ch] - ztrim*fitData[1][vfat][ch] < trimVcal[vfat]): trimDACs[vfat][ch] -= pow(2,4-i)

# Now take a scan with trimDACs found by binary search
for vfat in range(0,24):
    for ch in range(CHAN_MIN,CHAN_MAX):
        writeVFAT(ohboard,options.gtx,vfat,"VFATChannels.ChanReg%d"%(ch),trimDACs[vfat][ch])

runSCurve("SCurveData_Trimmed.root", doFit=False)

vfatConfig = open('%s/vfatConfig.txt'%dirPath,'w')
vfatConfig.write('vfatN/I:vt1/I:trimRange/I\n')
for vfat in range(0,24):
    vfatConfig.write('%i\t%i\t%i\n'%(vfat,vt1[vfat],tRanges[vfat]))
    pass
vfatConfig.close()

scanFilename = '%s/scanInfo.txt'%dirPath
outF = open(scanFilename,'w')
outF.write('vfat/I:tRange/I:sup/D:inf/D:trimVcal/D:trimCH/D\n')
for vfat in range(0,24):
    outF.write('%i  %i  %f  %f  %f  %i\n'%(vfat,tRanges[vfat],goodSup[vfat],goodInf[vfat],trimVcal[vfat],trimCH[vfat]))
    pass
outF.close()

exit(0)
