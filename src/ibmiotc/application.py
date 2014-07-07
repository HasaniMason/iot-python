# *****************************************************************************
# Copyright (c) 2014 IBM Corporation and other Contributors.
#
# All rights reserved. This program and the accompanying materials
# are made available under the terms of the Eclipse Public License v1.0
# which accompanies this distribution, and is available at
# http://www.eclipse.org/legal/epl-v10.html 
#
# Contributors:
#   David Parker - Initial Contribution
# *****************************************************************************

import re
import ibmiotc
import json
import ConfigParser
import iso8601
from datetime import datetime


# Compile regular expressions for topic parsing
DEVICE_EVENT_RE = re.compile("iot-2/type/(.+)/id/(.+)/evt/(.+)/fmt/(.+)")
DEVICE_COMMAND_RE = re.compile("iot-2/type/(.+)/id/(.+)/cmd/(.+)/fmt/(.+)")
DEVICE_STATUS_RE = re.compile("iot-2/type/(.+)/id/(.+)/mon")
APP_STATUS_RE = re.compile("iot-2/app/(.+)/mon")
		
class Message:
	def __init__(self, message):
		self.payload = json.loads(str(message.payload))
		self.timestamp = self.__parseMessageTimestamp()
		self.data = self.__parseMessageData()

		
	def __parseMessageTimestamp(self):
		try:
			if 'ts' in self.payload:
				return iso8601.parse_date(self.payload['ts'])
			else:
				return datetime.now()
		except iso8601.ParseError as e:
			raise ibmiotc.InvalidEventException("Unable to parse event timestamp: %s" % str(e))
	
	
	def __parseMessageData(self):
		if 'd' in self.payload:
			return self.payload['d']
		else:
			return None


class Status(Message):
	def __init__(self, message):
		result = DEVICE_STATUS_RE.match(message.topic)
		if result:
			Message.__init__(self, message)
			
			self.deviceType = result.group(1)
			self.deviceId = result.group(2)
			self.device = self.deviceType + ":" + self.deviceId
			
			'''
			Properties from the "Connect" status are common in "Disconnect" status too
			{
			u'ClientAddr': u'195.212.29.68', 
			u'Protocol': u'mqtt-tcp', 
			u'ClientID': u'd:bcaxk:psutil:001', 
			u'User': u'use-token-auth', 
			u'Time': u'2014-07-07T06:37:56.494-04:00', 
			u'Action': u'Connect', 
			u'ConnectTime': u'2014-07-07T06:37:56.493-04:00', 
			u'Port': 1883
			}
			'''

			self.clientAddr = self.payload['ClientAddr'] if ('ClientAddr' in self.payload) else None  
			self.protocol = self.payload['Protocol'] if ('Protocol' in self.payload) else None  
			self.clientId = self.payload['ClientID'] if ('ClientID' in self.payload) else None  
			self.user = self.payload['User'] if ('User' in self.payload) else None  
			self.time = iso8601.parse_date(self.payload['Time']) if ('Time' in self.payload) else None  
			self.action = self.payload['Action'] if ('Action' in self.payload) else None  
			self.connectTime = iso8601.parse_date(self.payload['ConnectTime']) if ('ConnectTime' in self.payload) else None  
			self.port = self.payload['Port'] if ('Port' in self.payload) else None  
			
			'''
			Additional "Disconnect" status properties
			{
			u'WriteMsg': 0, 
			u'ReadMsg': 872, 
			u'Reason': u'The connection has completed normally.', 
			u'ReadBytes': 136507, 
			u'WriteBytes': 32, 
			}
			'''
			self.writeMsg = self.payload['WriteMsg'] if ('WriteMsg' in self.payload) else None  
			self.readMsg = self.payload['ReadMsg'] if ('ReadMsg' in self.payload) else None  
			self.reason = self.payload['Reason'] if ('Reason' in self.payload) else None  
			self.readBytes = self.payload['ReadBytes'] if ('ReadBytes' in self.payload) else None  
			self.writeBytes = self.payload['WriteBytes'] if ('WriteBytes' in self.payload) else None  
			
		else:
			raise ibmiotc.InvalidEventException("Received device status on invalid topic: %s" % (message.topic))

	
class Event(Message):
	def __init__(self, message):
		result = DEVICE_EVENT_RE.match(message.topic)
		if result:
			Message.__init__(self, message)
			
			self.deviceType = result.group(1)
			self.deviceId = result.group(2)
			self.device = self.deviceType + ":" + self.deviceId
			
			self.event = result.group(3)
			self.format = result.group(4)
		else:
			raise ibmiotc.InvalidEventException("Received device event on invalid topic: %s" % (message.topic))


class Command(Message):
	def	__init__(self, message):
		result = DEVICE_COMMAND_RE.match(message.topic)
		if result:
			Message.__init__(self, message)
			
			self.deviceType = result.group(1)
			self.deviceId = result.group(2)
			self.device = self.deviceType + ":" + self.deviceId
			
			self.command = result.group(3)
			self.format = result.group(4)
		else:
			raise ibmiotc.InvalidEventException("Received device event on invalid topic: %s" % (message.topic))


class Client(ibmiotc.AbstractClient):

	def __init__(self, options):
		self.__options = options

		if self.__options['org'] == None:
			raise ibmiotc.ConfigurationException("Missing required property: org")
		if self.__options['id'] == None: 
			raise ibmiotc.ConfigurationException("Missing required property: type")
		
		if self.__options['org'] != "quickstart":
			if self.__options['auth-method'] == None: 
				raise ibmiotc.ConfigurationException("Missing required property: auth-method")
				
			if (self.__options['auth-method'] == "apikey"):
				if self.__options['auth-key'] == None: 
					raise ibmiotc.ConfigurationException("Missing required property for API key based authentication: auth-key")
				if self.__options['auth-token'] == None: 
					raise ibmiotc.ConfigurationException("Missing required property for API key based authentication: auth-token")
			else:
				raise ibmiotc.UnsupportedAuthenticationMethod(options['authMethod'])

		# Call parent constructor
		ibmiotc.AbstractClient.__init__(
			self, 
			organization = options['org'],
			clientId = "a:" + options['org'] + ":" + options['id'], 
			username = options['auth-key'] if (options['auth-method'] == "apikey") else None,
			password = options['auth-token']
		)
		
		# Add handler for device events
		self.client.message_callback_add("iot-2/type/+/id/+/evt/+/fmt/+", self.__onDeviceEvent)
		self.client.message_callback_add("iot-2/type/+/id/+/mon", self.__onDeviceStatus)
		self.client.message_callback_add("iot-2/app/+/mon", self.__onAppStatus)
		
		# Add handler for commands if not connected to QuickStart
		if self.__options['org'] != "quickstart":
			self.client.message_callback_add("iot-2/type/+/id/+/cmd/+/fmt/+", self.__onDeviceCommand)
		
		# Attach fallback handler
		self.client.on_message = self.__onUnsupportedMessage
		
		# Initialize user supplied callbacks (devices)
		self.deviceEventCallback = None
		self.deviceCommandCallback = None
		self.deviceStatusCallback = None
		
		# Initialize user supplied callbacks (applcations)
		self.appStatusCallback = None
		
		self.connect()
	
	
	def subscribeToDeviceEvents(self, deviceType="+", deviceId="+", event="+"):
		if self.__options['org'] == "quickstart" and deviceId == "+":
			self.logger.warning("QuickStart applications do not support wildcard subscription to events from all devices")
			return False
		
		if not self.connectEvent.wait():
			self.logger.warning("Unable to subscribe to events (%s, %s, %s) because application is not currently connected" % (deviceType, deviceId, event))
			return False
		else:
			topic = 'iot-2/type/%s/id/%s/evt/%s/fmt/json' % (deviceType, deviceId, event)
			self.client.subscribe(topic, qos=0)
			return True
	
	
	def subscribeToDeviceStatus(self, deviceType="+", deviceId="+"):
		if self.__options['org'] == "quickstart" and deviceId == "+":
			self.logger.warning("QuickStart applications do not support wildcard subscription to device status")
			return False
		
		if not self.connectEvent.wait():
			self.logger.warning("Unable to subscribe to device status (%s, %s) because application is not currently connected" % (deviceType, deviceId))
			return False
		else:
			topic = 'iot-2/type/%s/id/%s/mon' % (deviceType, deviceId)
			self.client.subscribe(topic, qos=0)
			return True
	
	
	def publishEvent(self, deviceType, deviceId, event, data):
		if not self.connectEvent.wait():
			return False
		else:
			topic = 'iot-2/type/%s/id/%s/evt/%s/fmt/json' % (deviceType, deviceId, event)
			
			# Note: Python JSON serialization doesn't know what to do with a datetime object on it's own
			payload = { 'd' : data, 'ts': datetime.now().isoformat() }
			self.client.publish(topic, payload=json.dumps(payload), qos=0, retain=False)
			return True
	
	
	def publishCommand(self, deviceType, deviceId, command, data=None):
		if self.__options['org'] == "quickstart":
			self.logger.warning("QuickStart applications do not support sending commands")
			return False
		if not self.connectEvent.wait():
			return False
		else:
			topic = 'iot-2/type/%s/id/%s/cmd/%s/fmt/json' % (deviceType, deviceId, command)

			# Note: Python JSON serialization doesn't know what to do with a datetime object on it's own
			payload = { 'd' : data, 'ts': datetime.now().isoformat() }
			self.client.publish(topic, payload=json.dumps(payload), qos=0, retain=False)
			return True

			
	'''
	Internal callback for messages that have not been handled by any of the specific internal callbacks, these
	messages are not passed on to any user provided callback
	'''
	def __onUnsupportedMessage(self, client, userdata, message):
		self.logger.warning("Received messaging on unsupported topic '%s' on topic '%s'" % (message.payload, message.topic))
		self.recv = self.recv + 1
	
	
	'''
	Internal callback for device event messages, parses source device from topic string and 
	passes the information on to the registerd device event callback
	'''
	def __onDeviceEvent(self, client, userdata, message):
		self.recv = self.recv + 1
		
		try:
			event = Event(message)
			self.logger.debug("Received event '%s' from %s:%s" % (event.event, event.deviceType, event.deviceId))
			if self.deviceEventCallback: self.deviceEventCallback(event)
		except ibmiotc.InvalidEventException as e:
			self.logger.critical(str(e))

		
	'''
	Internal callback for device command messages, parses source device from topic string and 
	passes the information on to the registerd device command callback
	'''
	def __onDeviceCommand(self, client, userdata, message):
		self.recv = self.recv + 1

		try:
			command = Command(message)
			self.logger.debug("Received command '%s' from %s:%s" % (command.command, command.deviceType, command.deviceId))
			if self.deviceCommandCallback: self.deviceCommandCallback(command)
		except ibmiotc.InvalidEventException as e:
			self.logger.critical(str(e))

		
	'''
	Internal callback for device status messages, parses source device from topic string and 
	passes the information on to the registerd device status callback
	'''
	def __onDeviceStatus(self, client, userdata, message):
		self.recv = self.recv + 1

		try:
			status= Status(message)
			self.logger.debug("Received %s action from %s:%s" % (status.action, status.deviceType, status.deviceId))
			if self.deviceStatusCallback: self.deviceStatusCallback(status)
		except ibmiotc.InvalidEventException as e:
			self.logger.critical(str(e))
	
	
	'''
	Internal callback for application command messages, parses source application from topic string and 
	passes the information on to the registerd applicaion status callback
	'''
	def __onAppStatus(self, client, userdata, message):
		self.recv = self.recv + 1

		statusMatchResult = self.__appStatusPattern.match(message.topic)
		if statusMatchResult:
			self.logger.debug("Received application status '%s' on topic '%s'" % (message.payload, message.topic))
			status = json.loads(str(message.payload))
			if self.appStatusCallback: self.appStatusCallback(statusMatchResult.group(1), status)
		else:
			self.logger.warning("Received application status on invalid topic: %s" % (message.topic))


'''
Parse a standard application configuration file
'''
def ParseConfigFile(configFilePath):
	parms = ConfigParser.ConfigParser()
	sectionHeader = "application"

	try:
		with open(configFilePath) as f:
			parms.readfp(ibmiotc.ConfigFile(f, sectionHeader))
		
		organization = parms.get(sectionHeader, "org", None)
		appId = parms.get(sectionHeader, "id", None)
		authMethod = parms.get(sectionHeader, "auth-method", None)
		authKey = parms.get(sectionHeader, "auth-key", None)
		authToken = parms.get(sectionHeader, "auth-token", None)
		
	except IOError as e:
		reason = "Error reading application configuration file '%s' (%s)" % (configFilePath,e[1])
		raise ibmiotc.ConfigurationException(reason)
		
	return {'org': organization, 'id': appId, 'auth-method': authMethod, 'auth-key': authKey, 'auth-token': authToken}
			