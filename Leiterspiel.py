import spidev
import random
import time
from random import randint
from enum import Enum
import logging
import sqlite3
import os

class MCP23S17:
	def __init__(self, slave_address, busnumber, chipnumber):
		assert busnumber in [0, 1]  # Hier wird überprüft ob die Bus Nummer 0 oder 1 ist (wir benutzen bei uns 0)
		assert chipnumber in [0, 1] # In erster Line wird überprüft ob die chipnumber 0 oder 1 ist (wir benutzen bei uns 0)
		self.controlbyte_write = slave_address<<1 # Setzen vom Kontroll Byte zum schreiben (das byte zum schreiben ist die Adresse mit den letzten Bit auf 0)
		self.controlbyte_read = (slave_address<<1)+1  # Setzen vom Kontroll Byte zum lesen (das byte zum lesen ist die Adresse mit den letzten Bit auf 1)
		self.spi = spidev.SpiDev() # erstellen der SpiDev instance um auf die spi schnittstelle zuzugreiffen können
		self.spi.open(busnumber, chipnumber) # öffnen der vom SPI Verbindung mit der gegeben Busnumber & chipnummer
		self.spi.max_speed_hz = 10000000 # Setzen der maximalen Frequenz
		# configure default registers erstellen von einen Dictionary welche alle Passenden Registernummer enthält zu den GPA & GPB
		# die register die unten aufgelistet sind 8 bit groß
		self._regs = {'conf': {'A': 0x00, 'B': 0x01}, # Config register bei den einzelnen (hier werden die Pins festgelegt also welcher ein Input & Output ist (für A und B)
					'input': {'A': 0x12, 'B': 0x13}, # Eingabe registe hier stehen die Registernummer um von den input pin die eingabe zu lesen (für A und B) wenn es gesetzt ist es immer jeweils einer der bits gesetzt
					'output': {'A': 0x14, 'B': 0x15}} # Output register hier stehen die Register um jeweils von einen Pin strom an/aus zu machen

	# Hier wird ein Wert in die Konfiguration geschrieben geschrieben
	# portab muss entweder A oder B sein
	# value wird gesetzt achtung die alten Konfiguration werden hier noch mit übernommen!
	def write_config(self, portab, value):
		assert portab in ['A', 'B']
		reg = self._regs['conf'][portab]
		v = 0
		if type(value) is int:
			v = value
			#self.spi.xfer([self.controlbyte_write, reg, value]) # schreiben mit den controlbyte und setzen der Value (der alte Wert wird überschrieben)
		elif type(value) is dict or type(value) is list:
			if type(value) is list:
				value = enumerate(value)
			for index, itemValue in value:
				if itemValue:
					v |= (1 << index)
		self.spi.xfer([self.controlbyte_write, reg, v]) # schreiben mit den controlbyte und setzen der Value (der alte Wert wird überschrieben)

	def read_config(self, portab): # Die Funktion dient dazu um aus den Config Register die einzelnen Werte zu lesen
		assert portab in ['A', 'B'] # der portab muss entweder A oder B sein
		reg = self._regs['conf'][portab] # Lese der Registernummer um zu wissen welcher gsesetzt werden muss
		return self.spi.xfer([self.controlbyte_read, reg, 0])[2] # Lesen der config einstellungen, es wird ein Liste zurückgegebn von der Liste wird der 2. Wert benutzt

	def write_output(self, portab, value):
		assert portab in ['A', 'B'] ## der portab muss entweder A oder B sein
		reg = self._regs['output'][portab] # Lese der Registernummer um zu wissen welcher gsesetzt werden muss 
		self.spi.xfer([self.controlbyte_write, reg, value]) # Setzen vom output (hier wird das controlbyte zum schreiben benutzt) der neue wert überschreibnt den alten!

	def read_output(self, portab):
		assert portab in ['A', 'B']  ## der portab muss entweder A oder B sein
		reg = self._regs['output'][portab]# Lese der Registernummer um zu wissen welcher gsesetzt werden muss 
		return self.spi.xfer([self.controlbyte_read, reg, 0])[2] # Lesen vom output (der Wert liefert von jeden Pin 8(bit))

	def read_input(self, portab): # lesen vom einen Eingabe-Pin
		assert portab in ['A', 'B']  ## der portab muss entweder A oder B sein
		reg = self._regs['input'][portab]# Lese der Registernummer um zu wissen welcher gsesetzt werden muss (in den Falle zum lesen der eingabe)
		return self.spi.xfer([self.controlbyte_read, reg, 0])[2] # Gebe den Wert zurück (benutzt wird hir der controlbyte zum lesen) NOTE: Es werden alle zuständen zurückgegebn also von jedem Pin

	def set_output_pin(self, portab, pin, value): # Setzen von Wert des Pin X  
		v = self.read_output(portab) # lesen von altem Wert
		mask = 1 << pin # bilden der Maske
		if not value: # überprüfen ob der Wert gesetzt ist
			v &= ~(mask) # entfernen des Bits
		else: 
			v |= mask
		self.write_output(portab, v)

	def get_output_pin(self, portab, pin):
		return bool(self.read_output(portab) & (1 << pin))

	def get_input_pin(self, portab, pin):
		return bool(self.read_input(portab) & (1 << pin))

class Loop:
	class Callback: 
		def __init__(self, cb, triggerTime = None, triggerCountLimit = None): 
			self.cb = cb # Callback Variable wird festgelegt

			if triggerTime != None:                                         # setzen der Zeit wann der Callback ausgelöst wurde
				self.triggerTime = time.time() + triggerTime
			else:
				self.triggerTime = None

			logging.debug("Adding new:"  + cb.__name__ + "callback with time: " + str(time.time()) + str(self.triggerTime))
			self.triggerCountLimit = triggerCountLimit
			self.triggerCount = 0
			self.triggerRawTime = triggerTime
			self.id = 0

		def is_timered(self): #schaut ob der Callback Zeitlimitiert ist
			return self.triggerTime != None

		def is_trigger_able(self): # schaut ob die Funktion ausführbar ist (Von der Zeit)
			return self.is_timered() and time.time() >= self.triggerTime

		def is_limited(self): # schaut ob die Funktion nach mehrmaligem Aufrufen gelöscht werden kann
			return self.triggerCountLimit != None and self.triggerCountLimit > 0 

		def is_done(self): # Überprüft ob die Funktion beendet ist 
			return self.is_limited() and self.triggerCount >= self.triggerCountLimit

		def __call__(self): # Überschreibt bzw. aktualisiert die Call Funktion Hinweis: () 
			self.triggerCount += 1
			if not self.is_limited() and self.triggerRawTime != None:
				self.triggerTime = time.time() + self.triggerRawTime
			return self.cb()

	def __init__(self): # initialiseren der Liste und des Dictionaries der Callbacks
		self.cbList = []
		self.cbDict = {}
		self.destroyEvent = None

	def find_index(self): #sucht eine freie Position (ID) für das Event aus
		for i in range(pow(2, 32-1)):
			if not i in self.cbDict:
				return i
		return -1

	def RegisterEvent(self, event): # fügt das Event zur Liste und Dictionary hinzu
		
		event.id = self.find_index()
		if event.id == -1:
			return -1
		self.cbList.append(event)
		self.cbDict.update({ event.id : event})
		return event.id

	def IsRunningEvent(self, index): # überprüft, ob der Index im Dictionary vorhanden ist
		return index in self.cbDict

	def UnregisterEvent(self, timerIndex): # Entfernt ein Event nach dem Index wenn vorhanden (Warning falls nicht vorhanden)
		cb = self.cbDict.get(timerIndex, None)
		if cb == None:
			logging.warn("There is no event with index %d" % (timerIndex))
			return
		self.cbList.remove(cb)
		del self.cbDict[timerIndex]

		logging.debug(("--------------"))
		logging.debug("List contains:")
		for cb in self.cbList:
			logging.debug(str(cb.id))

		logging.debug("--------------")
		logging.debug("got removed:%d" % cb.id)
		

	def run_after(self, triggerTime : float, cb): # führt ein Callback nach der triggerTime aus
		return self.RegisterEvent(self.Callback(cb, triggerTime, 1))

	def run_in_loop(self, cb): # führt die Funktion in der while Schleife aus
		return self.RegisterEvent(self.Callback(cb, None, 1))

	def run_every(self, triggerTime : float, cb): # führt die Funktion im Intervall aus (z.B. alle 5 Sekunden)
		return self.RegisterEvent(self.Callback(cb, triggerTime, None))

	def remove_from_loop(self, index): #  Entfernt den das Event anhand des Index
		self.UnregisterEvent(index)

	def set_destroy_event(self, event): # Setzt ein Event, wenn das Programm am Ende ist
		self.destroyEvent = event

	def run(self): # führt alle Callbacks die vorhanden sind aus und entfernt diese, wenn diese beendet wurden 
		event_trigger_count = 0
		try:
			while True:
				cbList = []
				for cb in self.cbList:
					if cb in cbList:
						continue
					if cb.is_timered():
						if cb.is_trigger_able():
							cb()
							event_trigger_count += 1
					else:
						cb()
						event_trigger_count += 1

					if cb.is_done():
						logging.debug("cb is done:" + str(cb.id))
						cbList.append(cb) # append fügt die Events die später entfernt werden der Liste hinzu 
				for cb in cbList:
					self.UnregisterEvent(cb.id)
				time.sleep(0.1)
		except KeyboardInterrupt:
			print("event_trigger_count:", event_trigger_count)

		if self.destroyEvent:
			self.destroyEvent()

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) #Für SQlite
class Game:
	def __init__(self):
		self.config = {
			"taster" : ('A', 7), # B = portab 7 = taster pin
			"led_area" : 'B' # Enter here your portab for your leds.
		}
		self.mcp = MCP23S17(0b0100000, 0, 0)
		self.mcp.write_config(self.config["led_area"], 0) # setzt alle auf Output
		self.__database = sqlite3.connect(os.path.join(BASE_DIR, "highscore.db"))
		# Create table
		cursor = self.__database.cursor()
		with open(os.path.join(BASE_DIR, "setup.sql"), 'r') as sql_file:
			cursor.executescript(sql_file.read())
			self.__database.commit()

		self.player_name = "Falk" # Spieler Name wird in der Datenbank angelegt (für die Highscore Liste)
		if not self.player_name:
			self.player_name = input("Enter a player name: ") # Falls kein Spielername angegeben wurde wird danach gefragt
		self.loop = Loop() # Erstellen einer Loop Instanz ()
		self.loop.set_destroy_event(lambda area = self.config["led_area"]: self.mcp.write_output(area, 0)) # lambda = anonyme Funktion (vereinfachung) ---- Am Ende wird alles auf 0 gesetzt (LED's gehen aus)
		self.run = self.loop.run # run funktioniert wird von der loop übernommen
		self.loop.run_every(0.0, self.update) # Update wird registiert und ausgeführt
		self.is_started = False # Hilfsvariable um den Stand der aktuellen LED abzufragen
		self.led_delay = randint(50, 100) / 100 # Zufalls Integer für den start eines neuen Levels (bevor die nächste led an geht)
		self.level = 0 # aktuelle level
		self.turnOffID = -1 # Index vom turn_off Event wird gespeichert
		self.is_level_up = False # Hilfsvariable um zu prüfen ob das nächste das Level erreicht wurde
		self.start() # hier wird die aktuelle gestartet

	def save(self): # Speichert das aktuelle Level in der Datenbank
		cursor = self.__database.cursor()
		cursor.execute("""
			INSERT INTO highscore(player_name, score) VALUES('%s', %d);
		""" % (self.player_name, self.level))
		self.__database.commit()


	def start(self): # Hier wird das Spiel gestartet und die Funktion turn_on als Callback in der Loop gespeichert
		self.turnOnID = self.loop.run_after(self.led_delay, self.turn_on)
		self.is_playing = True

	def update(self): # Zuerst wird geschaut, ob der Index der Funktion turn_on und turn_off noch aktiv sind
		if self.turnOnID != -1  and not self.loop.IsRunningEvent(self.turnOnID):
			self.turnOnID = -1
		if self.turnOffID != -1 and not self.loop.IsRunningEvent(self.turnOffID):
			self.turnOffID = -1

		if self.is_level_up: # Hier wird geprüft, ob der Spieler im nächsten Level ist, falls ja wird das Level erhöht und das Spiel wird von neuen Level gestartet
			self.cancel()
			self.level += 1
			if self.level >= 8:
				self.save()
				self.level = 0
			self.is_started = False
			self.update_level()
			logging.info("You are now level: %d", self.level)
			self.start()
			self.is_level_up = False
			return

		if self.is_playing: # Es wird geprüft, ob der Spieler im Spiel ist
			tasterPressed = self.mcp.get_input_pin(*self.config["taster"]) # prüft ob der Taster gedrückt ist
			if self.is_started: #LED an oder aus
				if tasterPressed: #Taster an ja oder nein
					self.is_level_up = True
			else:
				if tasterPressed: # wenn der Taster gedrückt wird aber Led nicht an ist = also verloren
					logging.info("You lost the game!")
					self.save()
					self.is_playing = False
					self.cancel()
					self.level = 0
					self.is_started = False
					self.update_level()
		else: # passiert wenn er verliert
			self.start()

	def cancel(self): # Bricht bei Abschluss des Levels das Blinken ab
		if self.turnOnID != -1:
			self.loop.remove_from_loop(self.turnOnID)
			self.turnOnID = -1
		if self.turnOffID != -1:
			self.loop.remove_from_loop(self.turnOffID)
			self.turnOffID = -1

	def update_level(self): # Anzeige der LED's wird aktuallisiert
		regVal = 0 #register Value 
		if self.is_started: 
			regVal |= (1 << self.level) # setzt die Value auf die aktuelle LED 
		for i in range(self.level): # Liste für alle LED's
			regVal |= (1 << i)
		saveValue = self.mcp.read_output(self.config["led_area"]) # holt den alten Wert
		if saveValue != regVal: # überpüft den alten mit dem neuen Wert
			self.mcp.write_output(self.config["led_area"], regVal) # setzt den neuen Wert, falls die Werte ungleich sind

	def get_delay_play_time(self): #  delay für das angehen der LED's
		return self.led_delay - (self.level * 0.015)

	def turn_on(self, restart = True): # Beginn des Spiels (Wann die erste LED an geht)
		self.is_started = 1
		self.update_level()
		if restart:
			self.turnOffID = self.loop.run_after(self.get_delay_play_time(), self.turn_off)
		logging.info("calling turn_on")

	def turn_off(self, restart = True): # Wenn das Spiel beendet wird, also ein Level abeschlossen wird
		self.is_started = 0
		self.update_level()
		if restart:
			self.turnOnID = self.loop.run_after(self.get_delay_play_time(), self.turn_on)
		logging.info("calling turn_off") # logging ähnlich wie Print

if __name__ == "__main__":
	logging.getLogger().setLevel(logging.INFO)
	game = Game()
	game.run()
