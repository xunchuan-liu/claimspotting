import requests
import json
import string
import csv
import numpy as np
import sys 
import nltk
#nltk.download('punkt')
import re
from nltk.tokenize import sent_tokenize
import spacy
nlp = spacy.load("en_core_web_sm")
from textblob import TextBlob
from html.parser import HTMLParser
from bs4 import BeautifulSoup
from datetime import date, timedelta
from Database import DBConnector

class Scraper:

	api_key = "lZhfHdqsylDdCK7Rkb8v7BArGTrOcpUQCZ8ZQGU7"
	database_file = "./Database/CR.db"
	dataExists = None
	selectionCriteria = None

	## Everything is done on initialization
	def __init__(self, date, exists=None):
		self.dailyClaims = None #Contains 10 best claims we will use for the daily newsletter 

		self.date=str(date) #This is today's date but we always pull yesterday's record
		self.yesterday = "`"+(date - timedelta(days=1)).strftime("%Y_%m_%d")+"`" #Name of our database table using yesterday's date

		self.db = DBConnector(Scraper.database_file) #Create connection to database
		self.db.createConnection()	

		if exists is None:
			yesterday = (date - timedelta(days=1)).strftime("%Y_%m_%d")	
			Scraper.dataExists = self.db.tableExists(yesterday) #Check if we've already added the day's data to table
		else:
			Scraper.dataExists = exists


		if Scraper.dataExists:
			print("Today's data already exists")
		
		else:
			print("Scraping...")			
			
			### Create table for the day
			self.db.createTable(self.yesterday)			

			### Set parameters to use api URL	
			date, packageParameters, granuleParameters = self.setParameters(self.date)	
			
			### Pulls the entire package containing the Congressional Record for the day
			packageID = self.pullRecord(date, packageParameters)
			
			### Pulls the list of granules for the congressional issue
			granules = self.pullGranules(packageID, granuleParameters)

			### Adds each HOUSE and SENATE item to database
			self.addSentences(granules)					

			print("Scraping Completed")
		
		self.db.closeConnection() #Close database connection

	## Gets the html link for the given granule link
	@staticmethod
	def getHTM(link):
		r = requests.get(link)
		o = r.json()
		download = o.get("download")
		txtLink = download.get("txtLink")
		return txtLink

	## Gets the pdf link for the given pdf link
	@staticmethod
	def getPDF(link):
		r = requests.get(link)
		o = r.json()
		download = o.get("download")
		pdfLink = download.get("pdfLink")
		return pdfLink

	## Sets the day, api key, and params to use for requests
	@staticmethod
	def setParameters(day):		
		print("Date: "+day)
		api_key = Scraper.api_key	
		api_key = "lZhfHdqsylDdCK7Rkb8v7BArGTrOcpUQCZ8ZQGU7"	
		startDate = day+"T00:00:00Z"

		packageParameters = {
			"api_key": api_key,
			"offset": 0,
			"pageSize": 1
		}

		granuleParameters = {
			"api_key": api_key,
			"offset": 0,
			"pageSize": 200
		}

		return startDate, packageParameters, granuleParameters


	## Pull the record for the given date
	@staticmethod
	def pullRecord(date, param):
		print("https://api.govinfo.gov/collections/CREC/"+date+"?offset=0&pageSize=1&api_key="+Scraper.api_key)
		response = requests.get("https://api.govinfo.gov/collections/CREC/"+date, params=param) #Gets a list of Congressional Record issues given the date

		print("Status Code: "+str(response.status_code)) #200 means no error occurred
		object = response.json() #Returns api response as a json object


		# We want to pull 1 new record per day to tokenize
		# Congress doesn't always meet so there could be days of 0 new records
		if object.get("count") == 0:
			print("No record for the day")
			raise Exception()
			return
		if object.get("count") != 1 and param["pageSize"] != 1:
			print("Error: More than 1 record pulled")
			raise Exception()		
			return
		else:
			print("Got the record for the day!")		


		packages = object.get("packages") #Gets list of packages from the json object - should only be one
		packageID = packages[0].get("packageId")

		return packageID


	## Get all the granules for the given package
	@staticmethod
	def pullGranules(package, param):
		response = requests.get("https://api.govinfo.gov/packages/"+package+"/granules", params=param)

		print("Status Code: "+str(response.status_code)) # 200 means no error occurred
		object = response.json()

		count = object.get("count")
		print("Granule Total: "+str(count))

		granules = object.get("granules")
		print("https://api.govinfo.gov/packages/"+package+"/granules?api_key=lZhfHdqsylDdCK7Rkb8v7BArGTrOcpUQCZ8ZQGU7&offset=0&pageSize=200")
		return granules


	## Iterate through the granule list and add sentences, scores, context, inserts, and links to house and senate
	def addSentences(self, granules):	
		houseExists = False # Checking if house met that day
		senateExists = False # Checking if senate met that day	

		for g in reversed(granules):			
			granuleClass = g.get("granuleClass") #check if it's house or senate			
			if granuleClass != "HOUSE" and granuleClass != "SENATE":
				return			

			granuleLink = g.get("granuleLink")+"?api_key="+Scraper.api_key #get the link to be able to view the contents
			pdfLink = self.getPDF(granuleLink)+"?api_key="+Scraper.api_key #save the pdf link for the final deliverable
			txtLink = self.getHTM(granuleLink)+"?api_key="+Scraper.api_key #view the content in html format to make parsing easier	
			request = requests.get(txtLink) 
			html = request.text #gets the text of the granule in html format		
			soup = BeautifulSoup(html, "html.parser") #removes the html tags with parser		
			raw = soup.text.replace("\n", "") #removes extra line breaks
			text = re.sub(" +", " ", raw) #removes extra white space			

			sentences = sent_tokenize(text) #split into sentences
			del sentences[0] #Remove header section for each granule					

			for s in sentences:
				doc = nlp(s) 				
				word_count = Scraper.countWords(doc)
				match = self.filter(s)
				if word_count > 8 and match is None:					
					score = Scraper.score(s)
					context, insert = Scraper.cutContext(s, sentences) #Keep the context 4 sentences before and after and add shorter excerpts for newsletter
					context = "".join(context) #Combine back into 1 string	
					insert = "".join(insert) #Combine back into 1 string					

					if granuleClass == "HOUSE":
						if houseExists == False:
							houseExists = True

						data = ("HOUSE", s, score, context, insert, pdfLink) #Create row of data for db
						self.db.insertData(self.yesterday, data) #Insert the data into the table								
						

					if granuleClass == "SENATE":	
						if senateExists == False:
							senateExists = True					
						data = ("SENATE", s, score, context, insert, pdfLink) #Create row of data for db
						self.db.insertData(self.yesterday, data) #Insert the data into the table

		if houseExists == False:
			print("No house today")
		if senateExists == False:
			print("No senate today")

	## Get the number of words in the sentence - a word has to contain alphanumeric characters
	@staticmethod
	def countWords(doc):		
		count = 0
		for token in doc:	
			match = re.search("[a-zA-Z\d]", str(token))
			if match is not None:
				count += 1
		return count


	## Filter unnecessary sentences based on regular expression matches and other heuristics
	@staticmethod
	def filter(sentence):
		# Filters out a sentence mostly mentioning people (over 50% of the sentence)	
		doc = nlp(sentence)	
		length = Scraper.countWords(doc)

		count = 0
		for ent in doc.ents:
			if ent.label_ == "PERSON":
				count += 2
		if length != 0 and count/length > 0.50:
			return count 

		# Filter out sentences with all upper case letters
		if sentence.isupper():
			return sentence

		# Filter out sentences with excessive periods
		if len(sentence) != 0 and sentence.count(".")/len(sentence) > 0.2:
			return sentence

		# Filters out interrogative sentences that end in question marks
		if sentence[-1] == "?":
			return sentence

		# Filters out sentences that start with these sentences
		matchExpressions = ("Congressional Record, Volume ",
							"Congress has the power to enact",
							"A bill to",
							"By Mr.",
							"By Ms.",
							"By Mrs.",
							"The Clerk",
							"A letter from the ",
							"A bill to ",
							"In the opinion of the Chair",
							"The bill",
							"This bill",
							"An act to ",
							"Madam Speaker",
							 "Mr. Speaker",
							"The Chair",
							"Is there objection",
							"Pursuant to clause",
							"I hereby appoint",
							"Under clause",
							"The SPEAKER",
							"Section \d",
							"Recommendation \d",
							"An act to ",							
							"[^a-zA-Z]")	

		for e in matchExpressions: 
			match = re.match(e, sentence)
			if match is not None:
				return match


		#Filters out sentences that contain these expressions
		searchExpressions = ("The Following Name Officer",
							 "THE FOLLOWING NAMED OFFICER",
							 "H. Res.",
							 "thank my collegeagues",
							 "[Pp]ursuant",
							 "I am grateful",
							 "submitted an amendment",
							 "YEAS",
							 "NAYS",
							 "``"
							 "NOT VOTING",
							 "-- \([a-zA-Z\d]\)",
							 "result of the vote")

		for e in searchExpressions:
			match = re.search(e, sentence)
			if match is not None:
				return match

		return None


	## Cut the context to 4 sentences before and after the given sentence unless it's already shorter than that
	## Adds an excerpt to be used for newletter that's 1 sentence before and 1 sentence after
	@staticmethod
	def cutContext(sentence, text):
		i = text.index(sentence)
		length = len(text)

		short = text[max(0, i - 4):min(length, i + 4)]
		shorter = text[max(0, i - 1):min(length, i + 1)]

		return short, shorter
			

	## Gets score for the given sentence
	@staticmethod
	def score(sentence):
		if "%" in sentence:
			sentence = re.sub("%", "%25", sentence) #If the sentence has a percentage sign, encode it as %25 in the API URL request	

		link = "https://idir.uta.edu/claimbuster/API/score/text/"+sentence
		response = requests.get(link)

		if response.status_code == 200:
			object = response.json()
			score = object["results"][0].get("score")		
			return score
		else: #If failed to return a score, print sentence so we can investigate - will return a score of 0
			print(response.status_code)
			print(sentence)
			return 0

	## Selects a set of random data to sample from the given congressional body of given size and creates csv files if indicated	
	def sample(self, body, size, table, fileName=None, createFile=False):
		self.db.createConnection(Scraper.database_file)

		sql = "SELECT * FROM "+table+""" WHERE body=\""""+body+"""\" AND score<0.25
				ORDER BY RANDOM() LIMIT """+str(size)+" ;"				
		first = np.array(self.db.selectByCondition(sql))

		sql = "SELECT * FROM "+table+""" WHERE body=\""""+body+"""\" AND score>0.25 AND score<0.5
				ORDER BY RANDOM() LIMIT """+str(size)+" ;"				
		second = np.array(self.db.selectByCondition(sql))

		sql = "SELECT * FROM "+table+""" WHERE body=\""""+body+"""\" AND score>0.5 AND score<0.75
				ORDER BY RANDOM() LIMIT """+str(size)+" ;"				
		third = np.array(self.db.selectByCondition(sql))

		sql = "SELECT * FROM "+table+""" WHERE body=\""""+body+"""\" AND score>0.75
				ORDER BY RANDOM() LIMIT """+str(size)+" ;"				
		fourth = np.array(self.db.selectByCondition(sql))

		self.db.closeConnection()

		samples = np.vstack((first, second, third, fourth))
		formatted_context = Scraper.format(samples) #Adds bold tag to the context for HTML display
		samples[:, 4] = formatted_context

		if createFile and fileName is not None:		
			with open(fileName+'.csv', 'w', newline='') as f:
				fields = ["id", "body", "claim", "score", "granule", "excerpt", "pdfLink"]					
				writer = csv.writer(f)
				writer.writerow(fields)
				writer.writerows(samples)
		
		return samples	


	#Adds a bold tag to the sentence within the context
	@staticmethod
	def format(samples):
		formatted = []

		for i in range(samples.shape[0]):
			split = str(samples[i, 4]).split(str(samples[i, 2]))
			bolded = "<strong>"+samples[i, 2]+"</strong>"
			split.insert(1, bolded)
			joined = "".join(split)			
			formatted.append(joined)
		

		formatted = np.asarray(formatted)

		return formatted

	## Selects top 10 claims to be used for daily newsletter with the criteria
	def selectBest(self):
		self.db.createConnection()
		self.dailyClaims = self.db.selectDaily(self.yesterday)
		self.db.closeConnection()

	## Writes the daily claims, contexts, and links to a json object
	def writeJSON(self):		
		return json.dumps(self.dailyClaims)		


	## CURRENTLY UNUSED
	## Method to create files with data from database
	@staticmethod
	def writeFiles():
		pass



	'''
	The remaining functions were formerly used when everything is still stored in memory. No longer needed after using database to store data.
	'''



	## NO LONGER USED AFTER MAKING DB CONNECTION - LOOK AT SCRAPER.SELECT FOR NEW SAMPLING METHOD
	## USE ONLY IF DATA WAS STORED IN OBJECT VARIABLES
	## Sample a batch of sentences for crowdsourcing
	@staticmethod 
	def oldSample(size, a, fileName, createFile=False):
		scores = a[:, 1].astype("float")		

		first = a[scores < 0.25]		
		indices1 = np.random.choice(first.shape[0], size, False)
		first = first[indices1]

		second = a[(scores > 0.25) & (scores < 0.5)]		
		indices2 = np.random.choice(second.shape[0], size, False)
		second = second[indices2]

		third = a[(scores > 0.5) & (scores < 0.75)]		
		indices3 = np.random.choice(third.shape[0], size, False)
		third = third[indices3]

		fourth = a[scores > 0.75]		
		indices4 = np.random.choice(fourth.shape[0], size, False)
		fourth = fourth[indices4]

		samples = np.vstack((first, second, third, fourth))
		formatted_context = Scraper.format(samples)
		samples[:, 2] = formatted_context

		if createFile:		
			with open(fileName+'.csv', 'w', newline='') as f:
				fields = ["claim", "score", "granule", "excerpt", "pdfLink"]					
				writer = csv.writer(f)
				writer.writerow(fields)
				writer.writerows(samples)

		return samples	


	## NO LONGER USED AFTER ADDING DATABASE CONNECTION - USE IF YOU WANT TO STORE DATA IN OBJECT ITSELF
	## Scores all the sentences
	def scoreAll(self):
		if self.houseScore != None or self.senateScore != None:
			print("Sentences already scored")
			return

		scores = np.vectorize(Scraper.score) #Applies score function to a vector


		if len(self.house) != 0:
			house = np.asarray(self.house)			
			self.houseScore = scores(house) #Get scores	
				

		if len(self.senate) != 0:
			senate = np.asarray(self.senate)	
			self.senateScore = scores(senate) #Get scores

			
	## NO LONGER USED AFTER ADDING DATABASE CONNECTION - USE IF YOU WANT TO STORE DATA IN OBJECT ITSELF
	## Stacks the sentences, scores, contexts, inserts, and links into 1 array
	def stackAll(self):
		if self.houseAll != None or self.senateAll != None:
			print("Array already created")
			return

		self.house = np.asarray(self.house)
		self.senate = np.asarray(self.senate)
		self.houseContext = np.asarray(self.houseContext)
		self.senateContext = np.asarray(self.senateContext)
		self.houseNewsInsert = np.asarray(self.houseNewsInsert)
		self.senateNewsInsert = np.asarray(self.senateNewsInsert)
		self.houseLinks = np.asarray(self.houseLinks)
		self.senateLinks = np.asarray(self.senateLinks)		

		if self.house.size != 0:
			self.houseAll = np.stack((self.house, self.houseScore, self.houseContext, self.houseNewsInsert, self.houseLinks), axis=1)
		else:
			print("No House today")			
		if self.senate.size != 0:
			self.senateAll = np.stack((self.senate, self.senateScore, self.senateContext, self.senateNewsInsert, self.senateLinks), axis=1)	
		else:
			print("No Senate today")

	


	


	

		





