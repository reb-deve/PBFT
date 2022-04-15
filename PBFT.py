import threading
from threading import Lock
import socket
import json
import time
import hashlib
import sys

nodes_ports = [(2000 + i) for i in range (0,2000)]

clients_ports = [(20000 + i) for i in range (0,20)]

preprepare_format_file = "Desktop/PBFT/preprepare_format.json"
prepare_format_file = "Desktop/PBFT/prepare_format.json"
commit_format_file = "Desktop/PBFT/commit_format.json"
reply_format_file = "Desktop/PBFT/reply_format.json"
checkpoint_format_file = "Desktop/PBFT/checkpoint_format.json"
checkpoint_vote_format_file = "Desktop/PBFT/checkpoint_vote_format.json"
view_change_format_file = "Desktop/PBFT/view_change_format.json"
new_view_format_file = "Desktop/PBFT/new_view_format.json"


def run_PBFT(number_of_honest_nodes,number_of_non_responding_nodes,number_of_faulty_primary,number_of_slow_nodes,checkpoint_frequency0,clients_ports0,timer_limit_before_view_change0): # All the nodes participate in the consensus

    global timer_limit_before_view_change
    timer_limit_before_view_change = timer_limit_before_view_change0

    global clients_ports
    clients_ports = clients_ports0

    global n
    n = number_of_honest_nodes+number_of_non_responding_nodes+number_of_faulty_primary+number_of_slow_nodes # total nodes number

    global the_nodes_ids_list
    the_nodes_ids_list = [i for i in range (n)]

    global f
    f = (n - 1) // 3 # Number of permitted faulty nodes

    global requests # a dictionary where keys are the clients' ids and the value is the timestamp of their last request
    requests = {} # Initiate as an empty dictionary

    global checkpoint_frequency
    checkpoint_frequency=checkpoint_frequency0

    global sequence_number
    sequence_number = 0 # Initiate the sequence number to 0 and increment it with each new request - we choosed 0 so that we can have a stable checkpoint at the beginning (necessary for a view change)

    global nodes_list
    nodes_list = []

    # Starting all the consensus nodes:

    #Start faulty primary nodes:
    for i in range (number_of_faulty_primary):
        globals()["n%s" % str(i)]=FaultyPrimary(node_id=i)
        nodes_list.append(globals()["n%s" % str(i)])
    # All the consensus nodes are on listening mode
    for node in nodes_list:
        threading.Thread(target=node.receive,args=()).start()

    #Start honest nodes:
    for i in range (number_of_honest_nodes):
        id = number_of_faulty_primary+i
        globals()["n%s" % str(id)]=HonestNode(node_id=id)
        nodes_list.append(globals()["n%s" % str(id)])
    # All the consensus nodes are on listening mode
    for node in nodes_list:
        threading.Thread(target=node.receive,args=()).start()

    #Start non responding nodes:
    for i in range (number_of_non_responding_nodes):
        id = number_of_faulty_primary+number_of_honest_nodes+i
        globals()["n%s" % str(id)]=NonRespondingNode(node_id=id)
        nodes_list.append(globals()["n%s" % str(id)])
    # All the consensus nodes are on listening mode
    for node in nodes_list:
        threading.Thread(target=node.receive,args=()).start()
    #Start slow nodes:
    for i in range (number_of_slow_nodes):
        id = number_of_faulty_primary+number_of_honest_nodes+number_of_non_responding_nodes+i
        globals()["n%s" % str(id)]=SlowNode(node_id=id)
        nodes_list.append(globals()["n%s" % str(id)])
    # All the consensus nodes are on listening mode
    for node in nodes_list:
        threading.Thread(target=node.receive,args=()).start()

def get_primary_id():
    node_0=nodes_list[0]
    return node_0.primary_node_id

def get_nodes_ids_list():
    return the_nodes_ids_list

def get_f():
    return f

class Node():
    def __init__(self,node_id):
        self.node_id = node_id
        self.node_port = nodes_ports[node_id]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        #s.settimeout(timer_limit_before_view_change)
        s.bind(("localhost", self.node_port))
        s.listen()
        self.socket = s
        self.view_number=0 # Initiated with 1 and increases with each view change
        self.primary_node_id=0
        self.preprepares={} # Dictionary of tuples of accepted preprepare messages: preprepares=[(view_number,sequence_number):digest]
        self.prepared_messages = [] # set of prepared messages
        self.replies={} # Maintain a dictionary of the last reply for each client: replies={client_id_1:[last_request_1,last_reply_1],...}
        self.message_reply = [] # List of all the reply messages
        self.prepares={} # Dictionary of accepted prepare messages: prepares = {(view_number,sequence_number,digest):[different_nodes_that_replied]}
        self.commits={} # Dictionary of accepted commit messages: commits = {(view_number,sequence_number,digest):[different_nodes_that_replied]}
        self.message_log = [] # Set of accepted messages
        self.last_reply_timestamp = {} # A dictionary that for each client, stores the timestamp of the last reply
        self.checkpoints = {} # Dictionary of checkpoints: {checkpoint:[list_of_nodes_that_voted]}
        self.checkpoints_sequence_number = [] # List of sequence numbers where a checkpoint was proposed
        self.stable_checkpoint = {"message_type":"CHECKPOINT", "sequence_number":0,"checkpoint_digest":"the_checkpoint_digest","node_id":self.node_id} # The last stable checkpoint
        self.stable_checkpoint_validators = [] # list of nodes that voted for the last stable checkpoint
        self.h=0 # The low water mark = sequence number of the last stable checkpoint
        self.H = self.h + 200 # The high watermark, proposed value in the original article
        self.accepted_requests_time = {} # This is a dictionary of the accepted preprepare messages with the time they were accepted so that one the timer is reached, the node starts a wiew change. The dictionary has the form : {"request":starting_time...}. the request is discarded once it is executed.
        self.received_view_changes = {} # Dictionary of received view-change messages (+ the view change the node itself sent) if the node is the primary node in the new view, it has the form: {new_view_number:[list_of_view_change_messages]}
        self.asked_view_change = [] # view numbers the node asked for
    def process_received_message(self,received_message):
            message_type = received_message["message_type"]
            if (message_type=="REQUEST"):
                if (received_message["request"] not in self.accepted_requests_time):
                    self.accepted_requests_time[(received_message["request"])]=time.time()
                timestamp = received_message["timestamp"]
                client_id = received_message["client_id"]
                if (client_id not in self.last_reply_timestamp or timestamp > self.last_reply_timestamp[client_id]): # The request is only processed if its timestamp is greater than teh timestamp of the last request that the node responded to
                    
                    if (self.node_id==self.primary_node_id):
                        
                        # S'assurer que le message est bon , digest....
                        client_id = received_message["client_id"]
                        actual_timestamp = received_message["timestamp"]
                        if (client_id in requests):
                            #print("Hello",self.node_id,self.primary_node_id)
                            last_timestamp = requests[client_id]
                        else:
                            last_timestamp = 0

                        if ((last_timestamp<actual_timestamp)or(last_timestamp==actual_timestamp and (received_message["request"] != reply["request"] for reply in self.message_reply))):
                            requests[client_id] = actual_timestamp
                            self.message_log.append(received_message)
                            self.broadcast_preprepare_message(request_message=received_message,nodes_ids_list=the_nodes_ids_list)
                     
                    else:
                        self.send(destination_node_id=self.primary_node_id,message=received_message)
            elif (message_type=="PREPREPARE"):
                timestamp = received_message["timestamp"]
                client_id = received_message["client_id"]
                request = received_message["request"]
                digest = hashlib.sha256(request.encode()).hexdigest()
                requests_digest = received_message["request_digest"]
                view = received_message["view_number"]
                tuple = (view,received_message["sequence_number"])

                # Making sure the digest's request is good + the view number in the message is similar to the view number of the node + We did not broadcast a message with the same view number and sequence number
                if ((digest==requests_digest) and (view==self.view_number) and (tuple not in self.preprepares)): 

                    self.message_log.append(received_message)
                    self.preprepares[tuple]=digest 
                    self.broadcast_prepare_message(preprepare_message=received_message,nodes_ids_list=the_nodes_ids_list)
                    if request not in self.accepted_requests_time:
                        self.accepted_requests_time[request] = time.time() # Start timer
                    
            elif (message_type=="PREPARE"):
                timestamp = received_message["timestamp"]
                client_id = received_message["client_id"]

                the_sequence_number=received_message["sequence_number"]
                the_request_digest=received_message["request_digest"]
                tuple = (received_message["view_number"],received_message["sequence_number"],received_message["request_digest"])

                node_id = received_message["node_id"]

                if ((received_message["view_number"]==self.view_number)): 
                    self.message_log.append(received_message)
                    
                    if (tuple not in self.prepares):
                        self.prepares[tuple]=[node_id]
                    else:
                        if (node_id not in self.prepares[tuple]):
                            self.prepares[tuple].append(node_id)
                    
                # Making sure the node inserted in its message log: a pre-prepare for m in view v with sequence number n
                p=0
                for message in self.message_log:
                    if ((message["message_type"]=="PREPREPARE") and (message["view_number"]==received_message["view_number"]) and (message["sequence_number"]==received_message["sequence_number"]) and (message["request"]==received_message["request"])):
                        p = 1
                        break
                # Second condition: Making sure the node inserted in its message log: 2f prepares from different backups that match the pre-preapare (same view, same sequence number and same digest)
                if (p==1 and len(self.prepares[tuple])==(n-f-1)): # The 2*f received messages also include the node's own received message
                    self.prepared_messages.append(received_message)
                    
                    self.broadcast_commit_message(prepare_message=received_message,nodes_ids_list=the_nodes_ids_list,sequence_number=the_sequence_number)

            elif (message_type=="COMMIT"):
                timestamp = received_message["timestamp"]
                client_id = received_message["client_id"]
                # TO DO:Make sure about the message signature + h<sequence number<H
                client_id = received_message["client_id"]
                timestamp = received_message["timestamp"]
                sequence_number = received_message["sequence_number"]

                # Make sure the message view number = the node view number
                if (self.view_number == received_message["view_number"]):

                    self.message_log.append(received_message)

                    tuple = (received_message["view_number"],received_message["sequence_number"],received_message["request_digest"])

                    if (tuple not in self.commits):
                        self.commits[tuple]=1
                    else:
                        self.commits[tuple]=self.commits[tuple]+1

                    i= 0

                    if (self.commits[tuple]==(2*f+1) and (tuple in self.prepares)):
                        if client_id not in self.last_reply_timestamp:
                            i=1
                        else:
                            if (self.last_reply_timestamp[client_id]<timestamp):
                                i=1
                        if i ==1:
                            reply = self.send_reply_message_to_client (received_message)
                       
                            if received_message["request"] in self.accepted_requests_time:
                                self.accepted_requests_time.pop(received_message["request"]) # Discard request from -self.accepted_requests_time- so that its timer stops
                            client_id = received_message["client_id"]
                            self.replies[client_id] = [received_message,reply]
                            self.last_reply_timestamp [client_id]=timestamp

                            if (sequence_number % checkpoint_frequency==0 and sequence_number not in self.checkpoints_sequence_number): # Creating a new checkpoint at each checkpoint creation period
                                with open(checkpoint_format_file):
                                    checkpoint_format= open(checkpoint_format_file)
                                    checkpoint_message = json.load(checkpoint_format)
                                    checkpoint_format.close()
                                checkpoint_message["sequence_number"] = sequence_number
                                checkpoint_message["node_id"] = self.node_id
                                checkpoint_content = [received_message["request_digest"],received_message["client_id"],reply] # We define the current state as the last executed request
                                checkpoint_message["checkpoint_digest"]= hashlib.sha256(str(checkpoint_content).encode()).hexdigest()
                                self.checkpoints_sequence_number.append(sequence_number)
                                self.broadcast_message(the_nodes_ids_list,checkpoint_message)
                                self.checkpoints[str(checkpoint_message)]=[self.node_id]
            elif (message_type=="CHECKPOINT"):
                lock = Lock()
                lock.acquire()
                for message in self.message_reply:
                    if (message["message_type"]=="REPLY" and message["sequence_number"]==received_message["sequence_number"]):
                        reply_list=[message["request_digest"],message["client_id"],message["result"]]
                        reply_digest = hashlib.sha256(str(reply_list).encode()).hexdigest()
                        if (reply_digest == received_message["checkpoint_digest"]):
                            with open(checkpoint_vote_format_file):
                                checkpoint_vote_format= open(checkpoint_vote_format_file)
                                checkpoint_vote_message = json.load(checkpoint_vote_format)
                                checkpoint_vote_format.close()
                            checkpoint_vote_message["sequence_number"] = received_message["sequence_number"]
                            checkpoint_vote_message["checkpoint_digest"] = received_message["checkpoint_digest"]
                            checkpoint_vote_message["node_id"] = self.node_id
                            self.send(received_message["node_id"],checkpoint_vote_message) 
                lock.release()
            elif (message_type=="VOTE"):
                lock = Lock()
                lock.acquire()
                for checkpoint in self.checkpoints:
                    checkpoint = checkpoint.replace("\'", "\"")
                    checkpoint = json.loads(checkpoint)
                    if (received_message["sequence_number"]==checkpoint["sequence_number"] and received_message["checkpoint_digest"]==checkpoint["checkpoint_digest"]):
                        node_id = received_message["node_id"]
                        if (node_id not in self.checkpoints[str(checkpoint)]):
                            self.checkpoints[str(checkpoint)].append(node_id)
                            if (len(self.checkpoints[str(checkpoint)]) == (2*f+1)):
                                #print("Node %d: This is a stable checkpoint !" % self.node_id)
                                # This will be the last stable checkpoint
                                self.stable_checkpoint = checkpoint
                                self.stable_checkpoint_validators = self.checkpoints[str(checkpoint)]
                                self.h = checkpoint["sequence_number"]
                                # TO Do: Delete checkpoints and messages log <= n
                                self.checkpoints.pop(str(checkpoint))
                                for message in self.message_log:
                                    if (message["message_type"] != "REQUEST"):
                                        if (message["sequence_number"]<= checkpoint["sequence_number"]):
                                            self.message_log.remove(message)
                                break
                
                lock.release()

            elif (message_type=="VIEW-CHANGE"):
                new_asked_view = received_message["new_view"]
                node_requester = received_message["node_id"]
                if (new_asked_view % len(the_nodes_ids_list) == self.node_id): # If the actual node is the primary node for the next view
                    
                 
                    if new_asked_view not in self.received_view_changes:
                        self.received_view_changes[new_asked_view]=[received_message]
                    else:
                        requested_nodes = [] # Nodes that requested changing the view
                        for request in self.received_view_changes[new_asked_view]:
                            requested_nodes.append(request["node_id"])
                        if node_requester not in requested_nodes:
                            self.received_view_changes[new_asked_view].append(received_message)
                    

                    if len(self.received_view_changes[new_asked_view])==2*f:

                        
                        print("New view!")

                        #The primary sends a view-change message for this view if it didn't do it before
                        if new_asked_view not in self.asked_view_change:
                            view_change_message = self.broadcast_view_change()
                            self.received_view_changes[new_asked_view].append(view_change_message)
                      
                        # Broadcast a new view message:
                        with open(new_view_format_file):
                            new_view_format= open(new_view_format_file)
                            new_view_message = json.load(new_view_format)
                            new_view_format.close()
                        new_view_message["new_view_number"]=new_asked_view

                        V=self.received_view_changes[new_asked_view]
                        new_view_message["V"]=V

                        # Creating the "O" set of the new view message:

                        # Initializing min_s and max_s:
                        min_s=0
                        max_s=0
                        if (len(V)>0):
                            sequence_numbers_in_V=[view_change_message["last_sequence_number"] for view_change_message in V]
                            min_s=min(sequence_numbers_in_V) # min sequence number of the latest stable checkpoint in V
                        sequence_numbers_in_prepare_messages=[message["sequence_number"] for message in self.message_log if message["message_type"]=="PREPARE"]
                        if len(sequence_numbers_in_prepare_messages)!=0:
                            max_s=max(sequence_numbers_in_prepare_messages)

                        O = []
                        
                        if (max_s>min_s):
                        #if(3>2):

                            # Creating a preprepare-view message for new_asked_view for each sequence number between max_s and min_s
                            for s in range (min_s,max_s):
                                with open(preprepare_format_file):
                                    preprepare_format= open(preprepare_format_file)
                                    preprepare_message = json.load(preprepare_format)
                                    preprepare_format.close()
                                preprepare_message["view_number"]=new_asked_view
                                preprepare_message["sequence_number"]=s

                                i=0 # There is no set Pm in P with sequence number s - In our code: there is no prepared message in P where sequence number = s (case 2 in the paper) => It turns i=1 if we find such a set
                                P = received_message["P"]
                                v=0 # Initiate the view number so that we can find the highest one in P
                                for message in P:
                                    if (message["sequence_number"])==s:
                                        i=1
                                        if (message["view_number"]>v):
                                            v = message["view_number"]
                                            d=message["request_digest"]
                                            r=message["request"]
                                            t=message["timestamp"]
                                            c=message["client_id"]

                                preprepare_message["request"]=r
                                preprepare_message["timestamp"]=t
                                preprepare_message["client_id"]=c

                                # Restart timers:
                                for request in self.accepted_requests_time:
                                    self.accepted_requests_time[request]=time.time()
                                    
                                if (i==0): # Case 2
                                    preprepare_message["request_digest"]="null"
                                    O.append(preprepare_message)
                                    self.message_log.append(preprepare_message)
                                
                                else: # Case 1
                                    preprepare_message["request_digest"]=d
                                    O.append(preprepare_message)
                                    self.message_log.append(preprepare_message)

                        new_view_message["O"]=O
                       

                        if (min_s>=self.stable_checkpoint["sequence_number"]):
                            # The primary node enters the new view
                            self.view_number=new_asked_view
                            self.primary_node_id=self.node_id
                            self.broadcast_message(the_nodes_ids_list,new_view_message)
                            self.asked_view_change.clear()
                          

            elif (message_type=="NEW-VIEW"):
                # TO DO : Make sure about the signature
                # TO DO : Verify the set O in the new view message

                # Restart timers:
                for request in self.accepted_requests_time:
                    self.accepted_requests_time[request]=time.time()
      
                O = received_message["O"]
                # Broadcast a prepare message for each preprepare message in O
                if len(O)!=0:
                    for message in O:
                        if (received_message["request_digest"]!="null"):
                            self.message_log.append(message)
                            prepare_message=self.broadcast_prepare_message(message,the_nodes_ids_list)
                            self.message_log.append(prepare_message)                
                self.view_number = received_message["new_view_number"]
                self.primary_node_id=received_message["new_view_number"]%n
                self.asked_view_change.clear()
                
    
    def receive(self,waiting_time=0): # The waiting_time parameter is for nodes we want to be slow, they will wait for a few seconds before processing a message =0 by default
        while True:
            #print(self.node_id,self.primary_node_id)
            # Start view change if one of the timers has reached the limit:
            i = 0 # Means no timer reached the limit , i = 1 means one of the timers reached their limit
            if len(self.accepted_requests_time)!=0 and len(self.asked_view_change)==0: # Check if the dictionary is not empty
                for request in self.accepted_requests_time:
                    actual_time = time.time()
                    timer = self.accepted_requests_time[request]
                    if (actual_time - timer) >= timer_limit_before_view_change:
                        
                        i = 1 # One of the timers reached their limit
                        new_view = self.view_number+1
                        break
            if i==1 and new_view not in self.asked_view_change:
                # Broadcast a view change:
                threading.Thread(target=self.broadcast_view_change,args=()).start()
                self.asked_view_change.append(new_view)
                for request in self.accepted_requests_time:
                    self.accepted_requests_time[request]=time.time()
            s=self.socket
            sender_socket = s.accept()[0]
            received_message = sender_socket.recv(2048).decode()
            received_message = received_message.replace("\'", "\"")
            received_message = json.loads(received_message)
            #print("Node %d got message: %s" % (self.node_id , received_message))
            sender_socket.close()
            #####################
            time.sleep(waiting_time)

            #print( self.node_id,self.asked_view_change)

            message_type = received_message["message_type"]
            if i == 1 or len(self.asked_view_change)!= 0: # Only accept checkpoints, view changes and new-view messages
                    if message_type in ["CHECKPOINT","VOTE","VIEW-CHANGE","NEW-VIEW"]:
                            threading.Thread(target=self.process_received_message,args=(received_message,)).start()
            else: # if i==0 and len(self.asked_view_change)!= 0
                        if message_type not in ["CHECKPOINT","VOTE","VIEW-CHANGE","NEW-VIEW"]:
                            if(message_type=="REQUEST" or received_message["view_number"] == self.view_number):   # Only accept messages with view numbers==the view number of the node
                                client_id = received_message["client_id"]
                                if (client_id in self.replies and received_message==self.replies[client_id][0]):
                                    #print("Node %d: Request already processed" % self.node_id)
                                    reply = self.replies[client_id][1]
                                    client_port = clients_ports[client_id]
                                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                    s.connect(("localhost", client_port))
                                    s.send(str(reply).encode())
                                    s.close()
                                else:
                                    threading.Thread(target=self.process_received_message,args=(received_message,)).start()
                        else:
                            threading.Thread(target=self.process_received_message,args=(received_message,)).start()
    
    def send(self,destination_node_id,message):
        destination_node_port = nodes_ports[destination_node_id]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        s.connect(("localhost", destination_node_port))
        s.send(str(message).encode())  
        s.close()  
    def broadcast_message(self,nodes_ids_list,message): # Send to all connected nodes # Acts as a socket server
        for destination_node_id in nodes_ids_list:
            #if (destination_node_id != self.node_id):
                self.send(destination_node_id,message)
    def broadcast_preprepare_message(self,request_message,nodes_ids_list): # The primary node prepares and broadcats a PREPREPARE message
        with open(preprepare_format_file):
            preprepare_format= open(preprepare_format_file)
            preprepare_message = json.load(preprepare_format)
            preprepare_format.close()
        preprepare_message["view_number"]=self.view_number
        global sequence_number
        preprepare_message["sequence_number"]=sequence_number
        preprepare_message["timestamp"]=request_message["timestamp"]
        tuple = (self.view_number,sequence_number)
        sequence_number = sequence_number + 1 # Increment the sequence number after each request 
        #Calculating the request's digest using SHA256
        request = request_message["request"]
        digest = hashlib.sha256(request.encode()).hexdigest()
        preprepare_message["request_digest"]=digest
        preprepare_message["request"]=request_message["request"]
        preprepare_message["client_id"]=request_message["client_id"]
        self.preprepares[tuple]=digest
        self.message_log.append(preprepare_message)
        self.broadcast_message(nodes_ids_list,preprepare_message)
        #self.send(self.node_id,preprepare_message)

    def broadcast_prepare_message(self,preprepare_message,nodes_ids_list): # The node broadcasts a prepare message
        # S'assurer des conditions avant d'envoyer le PREPARE message
        #prepare_message = prepare_format.read()
        with open(prepare_format_file):
            prepare_format= open(prepare_format_file)
            prepare_message = json.load(prepare_format)
            prepare_format.close()
        prepare_message["view_number"]=self.view_number
        prepare_message["sequence_number"]=preprepare_message["sequence_number"]
        prepare_message["request_digest"]=preprepare_message["request_digest"]
        prepare_message["request"]=preprepare_message["request"]
        prepare_message["node_id"]=self.node_id
        prepare_message["client_id"]=preprepare_message["client_id"]
        prepare_message["timestamp"]=preprepare_message["timestamp"]
        self.broadcast_message(nodes_ids_list,prepare_message)
        #self.send(self.node_id,prepare_message)

        return prepare_message

    def broadcast_commit_message(self,prepare_message,nodes_ids_list,sequence_number): # The node broadcasts a commit message
        with open(commit_format_file):
            commit_format= open(commit_format_file)
            commit_message = json.load(commit_format)
            commit_format.close()
        commit_message["view_number"]=self.view_number
        commit_message["sequence_number"]=sequence_number
        commit_message["node_id"]=self.node_id
        commit_message["client_id"]=prepare_message["client_id"]
        commit_message["request_digest"]=prepare_message["request_digest"]
        commit_message["request"]=prepare_message["request"]
        commit_message["timestamp"]=prepare_message["timestamp"]
        self.broadcast_message(nodes_ids_list,commit_message)

    def broadcast_view_change(self): # The node broadcasts a view change
        with open(view_change_format_file):
            view_change_format= open(view_change_format_file)
            view_change_message = json.load(view_change_format)
            view_change_format.close()
        new_view = self.view_number+1
        view_change_message["new_view"]=new_view
        view_change_message["last_sequence_number"]=self.stable_checkpoint["sequence_number"]
        view_change_message["C"]=self.stable_checkpoint_validators
        view_change_message["node_id"]=self.node_id
        if new_view not in self.received_view_changes:
            self.received_view_changes[new_view]=[view_change_message]
        else:
            self.received_view_changes[new_view].append(view_change_message)
        
        # We define P as a set of prepared messages at the actual node with sequence number higher than the sequence number in the last checkpoint
        view_change_message["P"]=[message for message in self.prepared_messages if message["sequence_number"]>self.stable_checkpoint["sequence_number"]]
        self.broadcast_message(the_nodes_ids_list,view_change_message)
        return view_change_message

    def send_reply_message_to_client (self,commit_message):
        client_id = commit_message["client_id"]
        client_port = clients_ports[client_id]
        with open(reply_format_file):
            reply_format= open(reply_format_file)
            reply_message = json.load(reply_format)
            reply_format.close()
        reply_message["view_number"]=self.view_number
        #reply_message["timestamp"]=
        reply_message["client_id"]=client_id
        reply_message["node_id"]=self.node_id
        reply = "Request executed"
        reply_message["result"]=reply
        reply_message["sequence_number"]=commit_message["sequence_number"]
        reply_message["request"]=commit_message["request"]
        reply_message["request_digest"]=commit_message["request_digest"]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("localhost", client_port))
        s.send(str(reply_message).encode())
        s.close()
        self.message_reply.append(reply_message)
        return reply
                             
class HonestNode(Node):
    def receive(self,waiting_time=0):
        Node.receive(self,waiting_time)

class SlowNode(Node):
    def receive(self,waiting_time=1):
        Node.receive(self,waiting_time)

class NonRespondingNode(Node):
    def receive(self):
        while True:
            s=self.socket
            #try:
            sender_socket = s.accept()[0]
            received_message = sender_socket.recv(2048).decode()
                #print("Node %d got message: %s" % (self.node_id , received_message))
            sender_socket.close()
                # receives messages but doesn't do anything with them
            #except:
            #    self.receive()

class FaultyPrimary(Node): # This node changes the client's request digest while sending a preprepare message
    def broadcast_preprepare_message(self,request_message,nodes_ids_list): # The primary node prepares and broadcats a PREPREPARE message
        with open(preprepare_format_file):
            preprepare_format= open(preprepare_format_file)
            preprepare_message = json.load(preprepare_format)
            preprepare_format.close()
        preprepare_message["view_number"]=self.view_number
        global sequence_number
        preprepare_message["sequence_number"]=sequence_number
        preprepare_message["timestamp"]=request_message["timestamp"]
        tuple = (self.view_number,sequence_number)
        sequence_number = sequence_number + 1 # Increment the sequence number after each request 
        #Calculating the request's digest using SHA256
        request = request_message["request"]+"abc"
        digest = hashlib.sha256(request.encode()).hexdigest()
        preprepare_message["request_digest"]=digest
        preprepare_message["request"]=request_message["request"]
        preprepare_message["client_id"]=request_message["client_id"]
        self.preprepares[tuple]=digest
        self.message_log.append(preprepare_message)
        self.broadcast_message(nodes_ids_list,preprepare_message)