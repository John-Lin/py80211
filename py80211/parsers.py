"""
    Parsers for the py80211 project
"""
import pcap
import sys
import struct

class InformationElements(object):
    """
        Parsing 802.11 frame Information Elements
    """
    def __init__(self):
        """
        build parser for IE tags
        """
        self.tagdata = {"unparsed":[]}  # dict to return parsed tags
        self.parser = {
            "\x00": self.ssid,  # ssid IE tag parser
            "\x01": self.rates,  # data rates tag parser
            "\x03": self.channel,  # channel tag parser
            "\x30": self.rsn,  # rsn tag parser
            "\x32": self.exrates  # extended rates tag parser
            }

    def parse_ie(self, rbytes):
        """
        takes string of raw bytes splits them into tags
        passes those tags to the correct parser
        retruns parsed tags as a dict, key is tag number
        rbytes = string of bytes to parse
        """
        self.tagdata = {"unparsed":[]}  # dict to return parsed tags
        # offsets = {} # TODO
        while len(rbytes) > 0:
            try:
                fbyte = rbytes[0]
                # add two to account for size byte and tag num byte
                blen = ord(rbytes[1]) + 2  # byte len of ie tag
                if fbyte in self.parser.keys():
                    prebytes = rbytes[0:blen]
                    if blen == len(prebytes):
                        self.parser[fbyte](prebytes)
                    else:
                        # mangled packets
                        return -1
                else:
                    # we have no parser for the ie tag
                    self.tagdata["unparsed"].append(rbytes[0:blen])
                rbytes = rbytes[blen:]
            except IndexError:
                # mangled packets
                return -1

    def exrates(self, rbytes):
        """
        parses extended supported rates
        exrates IE tag number is 0x32
        retruns exrates in a list
        """
        exrates = []
        for exrate in tuple(rbytes[2:]):
            exrates.append(ord(exrate))
        self.tagdata["exrates"] = exrates

    def channel(self, rbytes):
        """
            Parses channel
            Channel IE tag number is 0x03
            returns channel as int
            last byte is channel
        """
        self.tagdata["channel"] = ord(rbytes[2])

    def ssid(self, rbytes):
        """
            Parses ssid IE tag
            ssid IE tag number is 0x00
            Returns the ssid as a string
        """
        # how do we handle hidden ssids?
        self.tagdata["ssid"] = unicode(rbytes[2:], errors='replace')

    def rates(self, rbytes):
        """
            Parses rates from ie tag
            rates IE tag number is 0x01
            returns rates as in a list
        """
        self.tagdata["rates"] = [ (ord(rate)) for rate in tuple(rbytes[2:]) ]


    def rsn(self, rbytes):
        """
            Parses robust security network ie tag
            rsn ie tag number is 0x30
            returns rsn info in nested dict
            gtkcs is group temportal cipher suite
            akm is auth key managment, ie either wpa, psk ....
            ptkcs is pairwise temportal cipher suite
        """
        rsn = {}
        ptkcs = []
        akm = []
        # need to extend this
        cipherS = {
            1 : "WEP-40/64",
            2 : "TKIP",
            3 : "RESERVED",
            4 : "CCMP",
            5 : "WEP-104/128"
            }
        authKey = {
            1 : "802.1x or PMK",
            2 : "PSK",
            }
        try:
            version = struct.unpack('h', rbytes[2:4])[0]
            rsn["gtkcsOUI"] = rbytes[4:7]
            # GTK Bytes Parsing
            gtkcsTypeI = ord(rbytes[7])
            if gtkcsTypeI in cipherS.keys():
                gtkcsType = cipherS[gtkcsTypeI]
            else:
                gtkcsType = gtkcsTypeI
            rsn["gtkcsType"] = gtkcsType
            # PTK Bytes Parsing
            # len of ptk types supported
            ptkcsTypeL = struct.unpack('h', rbytes[8:10])[0]
            counter = ptkcsTypeL
            cbyte = 10 #current byte
            while counter >= ptkcsTypeL:
                ptkcsTypeOUI = rbytes[cbyte:cbyte+3]
                ptkcsTypeI = ord(rbytes[cbyte+3])
                if ptkcsTypeI in cipherS.keys():
                    ptkcsType = cipherS[ptkcsTypeI]
                else:
                    ptkcsType = ptkcsTypeI
                cbyte += 4 # end up on next byte to parse
                ptkcs.append({"ptkcsOUI":ptkcsTypeOUI,
                              "ptkcsType":ptkcsType})
                counter -= 1

            akmTypeL = struct.unpack('h', rbytes[cbyte:cbyte+2])[0]
            cbyte += 2
            counter = akmTypeL
            #this might break need testing
            while counter >= akmTypeL:
                akmTypeOUI = rbytes[cbyte:cbyte+3]
                akmTypeI = ord(rbytes[cbyte+3])
                if akmTypeI in authKey.keys():
                    akmType = authKey[akmTypeI]
                else:
                    akmType = akmTypeI
                cbyte += 4 # end up on next byte to parse
                akm.append({"akmOUI":akmTypeOUI,
                              "akmType":akmType})
                counter -= 1
            # 8 bits are switches for various features
            capabil = rbytes[cbyte:cbyte+2]
            cbyte += 3 # end up on PMKID list
            rsn["pmkidcount"] = rbytes[cbyte:cbyte +2]
            rsn["pmkidlist"] = rbytes[cbyte+3:]
            rsn["ptkcs"] = ptkcs
            rsn["akm"] = akm
            rsn["capabil"] = capabil
            self.tagdata["rsn"] = rsn
        except IndexError:
            # mangled packets
            return -1

class Common(object):
    """
        Class file for parsing
        several common 802.11 frames
    """
    def __init__(self, dev):
        """
            Open up the libpcap interface
            Open up the device to sniff from
            dev = device name as a string
        """
        # this gets set to True if were seeing mangled packets
        self.mangled = False
        # number of mangled packets seen
        self.mangledcount = 0
        # create ie tag parser
        self.IE = InformationElements()

        # This associates each packet to the parser it corresponds to it
        # Later we'll use that parsers to parse them
        self.parser = {
            0:{
                # managment frames
                0: self.placedef,   # association request
                1: self.placedef,   # association response
                2: self.placedef,   # reassociation request
                3: self.placedef,   # reaassociation response
                4: self.probe_request,   # probe request
                5: self.probe_response,  # probe response
                8: self.beacon,     # beacon
                9: self.placedef,   # ATIM
                10: self.placedef,  # disassoication
                11: self.placedef,  # authentication
                12: self.placedef,  # deauthentication
                },
            1:{},  # control frames
            2:{  # data frames
                0: self.data,  # data
                1: self.data,  # data + CF-ack
                2: self.data,  # data + CF-poll
                3: self.data,  # data + CF-ack+CF-poll
                5: self.data,  # CF-ack
                6: self.data,  # CF-poll
                7: self.data,  # CF-ack+CF-poll
                8: self.data,  # QoS Data
                9: self.data,  # QoS Data + CF-ack
                10: self.data,  # QoS Data + CF-poll
                11: self.data,  # QoS Data + CF-ack+CF-poll
                12: self.data,  # QoS Null
                14: self.data,  # QoS + CF-poll (no data)
                15: self.data,  # QoS + CF-ack (no data)
            }
        }

        self.packetBcast = {
            "oldbcast": '\x00\x00\x00\x00\x00\x00',  # old broadcast address
            "l2": '\xff\xff\xff\xff\xff\xff',     # layer 2 mac broadcast
            "ipv6m": '\x33\x33\x00\x00\x00\x16',  # ipv6 multicast
            "stp": '\x01\x80\xc2\x00\x00\x00',    # Spanning Tree multicast 802.1D
            "cdp": '\x01\x00\x0c\xcc\xcc\xcc',    # CDP/VTP mutlicast address
            "cstp": '\x01\x00\x0C\xCC\xCC\xCD',   # Cisco shared STP Address
            "stpp": '\x01\x80\xc2\x00\x00\x08',   # Spanning Tree multicast 802.1AD
            "oam": '\x01\x80\xC2\x00\x00\x02',    # oam protocol 802.3ah
            "ipv4m": '\x01\x00\x5e\x00\x00\xCD',  # ipv4 multicast
            "ota" : '\x01\x0b\x85\x00\x00\x00'    # Over the air provisioning multicast
        }
        self.openSniff(dev)

    def openSniff(self, dev):
        """
            open up a libpcap object
            return object and radio tap boolen
        """
        packet = None

        self.lp = pcap.pcapObject()
        # Open the capture device:
        snap_lenght = 1600
        promisc_flag = 0
        timeout = 100
        self.lp.open_live(dev, snap_lenght, promisc_flag, timeout)

        if self.lp.datalink() == 127:
            self.rth = True
            # snag a packet to look at header, this should always be a
            # packet that wasnt injected so should have a rt header
            while packet is None:
                frame = self.getFrame()
                if frame is not None:
                    packet = frame[1]
            # set known header size
            self.headsize = struct.unpack('h', packet[2:4])[0]
        else:
            self.rth = False
        return

    def isBcast(self, mac):
        """
        returns boolen if mac is a broadcast/multicast mac
        """
        if mac in self.packetBcast.values():
            return True
        # deal with ipv6multi cast addresses
        elif mac[:2] == self.packetBcast["ipv6m"][:2]:
            return True
        else:
            return False

    def placedef(self, data):
        pass
        #print data[self.rt].encode('hex')
        #print "No parser for subtype\n"

    def getFrame(self):
        """
        return a frame from libpcap
        """
        return self.lp.next()

    def parseFrame(self, frame):
        """
        Determine the type of frame and
        choose the right parser
        """
        if frame is not None:
            data = frame[1]
            if data is None:
                return None
            if self.rth:
                self.rt = struct.unpack('h', data[2:4])[0]
                # check to see if packet really has a radio tap header
                # lorcon injected packets wont
                if self.rt != self.headsize:
                    self.rt = 0
            else:
                self.rt = 0
        else:
            return None
        # determine frame subtype
        # subtype byte should be one off radio tap headers
        #subtype = data[self.rt:self.rt +1]
        ptype = ord(data[self.rt])
        # wipe out all bits we dont need
        ftype = (ptype >> 2) & 3
        stype = ptype >> 4

        if ftype in self.parser.keys():
            if stype in self.parser[ftype].keys():
                # will return -1 if packet is mangled
                # none if we cant parse it
                parsedFrame = self.parser[ftype][stype](data[self.rt:])
                # packet is mangled some how return the error
                if parsedFrame in [None, -1]:
                    return parsedFrame
                else:
                    parsedFrame["type"] = ftype
                    parsedFrame["stype"] = stype
                    # strip the headers
                    parsedFrame['rtap'] = self.rt
                    parsedFrame["raw"] = data
                return parsedFrame
            else:
                # we dont have a parser for the packet
                return None
        else:
            # we dont have a parser for the packet
            return None

    def data(self, data):
        """
        parse the src,dst,bssid from a data frame
        """
        # do a bit bitwise & to check which of the last 2 bits are set
        try:
            dsbits = ord(data[1]) & 3
            # from ds to station via ap
            if dsbits == 1:
                bssid = data[4:10]  # bssid addr 6 bytes
                src = data[10:16]  # src addr 6 bytes
                dst = data[16:22]  # destination addr 6 bytes
            # from station to ds va ap
            elif dsbits == 2:
                dst = data[4:10]  # destination addr 6 bytes
                bssid = data[10:16]  # bssid addr 6 bytes
                src = data[16:22]  # source addr 6 bytes
            # wds frame
            elif dsbits == 3:
                # we dont do anything with these yet
                return None
            else:
                # mangled ds bits
                self.mangled = True
                self.mangledcount += 1
                return -1
        except IndexError:
            self.mangled = True
            self.mangledcount += 1
            return -1
        return {"src":src, "dst":dst, "bssid":bssid, "ds":dsbits}

    def probe_response(self, data):
        """
        Parse out probe response
        return a dict of with keys of
        src, dst, bssid, probe request
        """
        try:
            dsbits = ord(data[1]) & 3
            dst = data[4:10]  # destination addr 6 bytes
            src = data[10:16]  # source addr 6 bytes
            bssid = data[16:22]  # bssid addr 6 bytes
            # parse the IE tags
            # possible bug, no fixed 12 byte paramaters before ie tags?
            # these seem to have it...
            self.IE.parse_ie(data[36:])
            if "ssid" not in self.IE.tagdata.keys():
                self.mangled = True
                self.mangledcount += 1
                return -1
            else:
                essid = self.IE.tagdata["ssid"]
            if "channel" not in self.IE.tagdata.keys():
                self.mangled = True
                self.mangledcount += 1
                return -1
            else:
                channel = self.IE.tagdata["channel"]
        except IndexError:
            self.mangled = True
            self.mangledcount += 1
            return -1
        return {"bssid":bssid, "essid":essid, "src":src,
            "dst":dst, "channel":channel, "extended":self.IE.tagdata, "ds":dsbits}

    def probe_request(self, data):
        """
        Parse out probe requests
        return a dict of with keys of
        src, dst, bssid, probe request
        """
        try:
            dsbits = ord(data[1]) & 3
            dst = data[4:10]  # destination addr 6 bytes
            src = data[10:16]  # source addr 6 bytes
            bssid = data[16:22]  # bssid addr 6 bytes
            # parse the IE tags
            # possible bug, no fixed 12 byte paramaters before ie tags?
            self.IE.parse_ie(data[24:])
            if "ssid" not in self.IE.tagdata.keys():
                self.mangled = True
                self.mangledcount += 1
                return -1
            else:
                essid = self.IE.tagdata["ssid"]
            if "channel" not in self.IE.tagdata.keys():
                self.mangled = True
                self.mangledcount += 1
                return -1
            else:
                channel = self.IE.tagdata["channel"]
        except IndexError:
            self.mangled = True
            self.mangledcount += 1
            return -1
        return {"bssid":bssid, "essid":essid, "src":src,
            "dst":dst, "channel":channel, "extended":self.IE.tagdata, "ds":dsbits}

    def beacon(self, data):
        """
            Parse out beacon packets
            return a dict with the keys of
            src, dst, bssid, essid, channel ....
            going to need to add more
        """
        try:
            dsbits = ord(data[1]) & 3
            dst = data[4:10]  # destination addr 6 bytes
            src = data[10:16]  # source addr 6 bytes
            bssid = data[16:22]  # bssid addr 6 bytes
            # parse the IE tags
            self.IE.parse_ie(data[36:])
            if "ssid" not in self.IE.tagdata.keys():
                self.mangled = True
                self.mangledcount += 1
                return -1
            else:
                essid = self.IE.tagdata["ssid"]
            if "channel" not in self.IE.tagdata.keys():
                self.mangled = True
                self.mangledcount += 1
                return -1
            else:
                channel = self.IE.tagdata["channel"]
        except IndexError:
            self.mangled = True
            self.mangledcount += 1
            return -1

        return {
            "bssid":bssid,
            "essid":essid,
            "src":src,
            "dst":dst,
            "channel":channel,
            "extended":self.IE.tagdata,
            "ds":dsbits
            }

if __name__ == "__main__":
    x = Common(sys.argv[1])
    while True:
        frame = x.parseFrame(x.getFrame())
        #if frame != None:
        #    if frame["key"] == "\x20":
        #        print frame
        print x.parseFrame(x.getFrame())