
import BaseHTTPServer
import cStringIO
import sys
import traceback
import urlparse
import pdb
import json

import os

import config
from utils import formats, graphs
from global_resources import NODE_TITLE, NODE_COMPREHENSION_KEY, NODE_DEPENDENCIES, NODE_RESOURCES, NODE_SEE_ALSO, NODE_SUMMARY
from utils.graphs import Node

"""A simple server to serve as a placeholder. Basically spits out graphs
in various formats. It responds to the following requests:

  GET nodes                      get a JSON object representing the full graph
  GET nodes/node-name                 get the JSON representation of a single node
  GET nodes/node-name/map             get the part of the graph that a node depends on
  GET nodes/node-name/related         get the part of the graph that's related to a node
                                         (ancestors/descendants)

TODO add POST/PUT/DELETE/OPTIONS information once API is complete

It can also produce SVG and DOT output for all the graph requests.
You can specify this with a query field in the URL, e.g.

  GET full_graph?format=svg

Start the server by typing (from the main knowledge-maps directory):

  python backend/simple_server.py 8000
"""


nodes = None
graph = None

def load_graph():
    global nodes, graph
    if nodes is None:
        nodes = formats.read_nodes(config.CONTENT_PATH)
        nodes = graphs.remove_missing_links(nodes)
        graph = graphs.Graph.from_node_dependencies(nodes)

# TODO where should we place this function?
def update_node(node_id, jdata):
    """
    Write the node data provided in jdata to the appropriate node_id
    """
    global nodes
    if nodes is None or not nodes.has_key(node_id):
        nodes = {node_id: Node()}
        nodes[node_id].tag = node_id
    nodes[node_id].add_json_data(jdata)

    nodes[node_id].write_node_to_file(jdata.keys())



class HTTPRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    server_version = 'AGFKDebug'

    def do_OPTIONS(self):
	""" Return HTTP Options"""
        self.send_response(200)
        self.add_cors_header()
        self.send_header('Allow','GET, PUT, POST, DELETE')
        self.end_headers()

    def do_DELETE(self):
	"""TODO"""
        pass

    def do_PUT(self):
	""" TODO: make unique from POST"""
        self.do_POST() # TODO return 204...

    def do_POST(self):
	""" POST node data """
        parse = urlparse.urlparse(self.path)
        parts = parse.path.lower().split('/')
        parts = filter(bool, parts)
        try:
            clen = int(self.headers.getheader('content-length'))
            if clen:
                post_body = self.rfile.read(clen)
                jdata = json.loads(post_body)

                # write the appropriate data TODO handle multiple nodes / related etc (will this be an issue?)
                if parts[0] == 'nodes' and len(parts)==2:
                    update_node(parts[1],jdata)
            self.send_response(201)
            self.add_cors_header()
            self.end_headers()
        except:
            self.send_error(500, traceback.format_exc())

    def do_GET(self):
	"""GET node data"""
        load_graph()
        parse = urlparse.urlparse(self.path)
        parts = parse.path.lower().split('/')
        parts = filter(bool, parts)

        query = urlparse.parse_qs(parse.query)
        if 'format' in query:
            fmt = query['format'][0]
        else:
            fmt = 'json'

        ctype = {'json': 'application/json',
                 'svg': 'image/svg+xml',
                 'dot': 'text/plain',
                 }[fmt]
        try:
            if parts[0] == 'nodes' and len(parts) == 1:
                assert len(parts)==1
                text = self.get_full_graph(fmt=fmt)
            elif parts[0] == 'nodes':
                node = parts[1]
                assert node in nodes
                if len(parts) == 2:
                    assert fmt == 'json'
                    text = self.get_node_json(parts[1])
                elif parts[2] == 'related':
                    assert len(parts) == 3
                    text = self.get_related_nodes(parts[1], fmt=fmt)
                elif parts[2] == 'map':
                    assert len(parts) == 3
                    text = self.get_map(parts[1], fmt=fmt)
                else:
                    raise RuntimeError('Invalid resource: %s' % self.path)
            else:
                raise RuntimeError('Invalid resource: %s' % self.path)
            self.send_text(text, ctype)
        except:
            self.send_error(404, traceback.format_exc())

    def add_cors_header(self):
	"""Add headers to all Cross Origin Resource Sharing"""
        self.send_header('Access-Control-Allow-Origin','*') # TODO do we want full CORS?
        self.send_header('Access-Control-Allow-Methods','GET,PUT,POST,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Credentials', 'true')
        self.send_header('Access-Control-Allow-Headers', 'x-requested-with,Content-Type')
        self.send_header('Access-Control-Max-Age','86400') # cache preflight for 24 hours

    def send_text(self, text, ctype):
	"""Send text data via HTTP response"""
        self.send_response(200)
        self.add_cors_header()
        self.send_header('Content-type', ctype + ';charset=utf-8') # TODO make encoding an option?
        self.send_header('Content-length', len(text))
        self.end_headers()
        self.wfile.write(text)

    def format_graph(self, nodes, graph, fmt):
	"""Return graph in desired format"""
        if fmt == 'json':
            f = cStringIO.StringIO()
            formats.write_graph_json(nodes, graph, f)
            return f.getvalue()
        elif fmt == 'dot':
            f = cStringIO.StringIO()
            formats.write_graph_dot(nodes, graph, f)
            return f.getvalue()
        elif fmt == 'svg':
            dotfile = os.path.join(config.TEMP_PATH, 'graph.dot')
            svgfile = os.path.join(config.TEMP_PATH, 'graph.svg')
            formats.write_graph_dot(nodes, graph, open(dotfile, 'w'))
            os.system('dot -Tsvg %s -o %s' % (dotfile, svgfile))
            return open(svgfile, 'rb').read()
        else:
            raise RuntimeError('Unknown format: %s' % fmt)

    def get_full_graph(self, fmt):
        load_graph()
        return self.format_graph(nodes, graph, fmt)

    def get_related_nodes(self, tag, fmt):
        load_graph()

        ancestors = graphs.ancestors_set(nodes, graph, tag)
        descendants = graphs.descendants_set(nodes, graph, tag)
        relevant = set([tag]).union(ancestors).union(descendants)
        rel_nodes = {tag: node for tag, node in nodes.items() if tag in relevant}
        rel_nodes = graphs.remove_missing_links(rel_nodes)
        rel_graph = graphs.Graph.from_node_dependencies(rel_nodes)

        return self.format_graph(rel_nodes, rel_graph, fmt)

    def get_node_json(self, tag):
        load_graph()
        return formats.node_to_json(nodes, tag)

    def get_map(self, tag, fmt):
        load_graph()

        ancestors = graphs.ancestors_set(nodes, graph, tag)
        relevant = set([tag]).union(ancestors)
        rel_nodes = {tag: node for tag, node in nodes.items() if tag in relevant}
        rel_nodes = graphs.remove_missing_links(rel_nodes)
        rel_graph = graphs.Graph.from_node_dependencies(rel_nodes)

        return self.format_graph(rel_nodes, rel_graph, fmt)

def run_server(port):
    server_address = ('', port)
    httpd = BaseHTTPServer.HTTPServer(server_address, HTTPRequestHandler)
    sa = httpd.socket.getsockname()
    print "Serving HTTP on", sa[0], "port", sa[1], "..."
    httpd.serve_forever()
    



if __name__ == '__main__':
    if len(sys.argv) >= 2:
        port = int(sys.argv[1])
    else:
        port = 8000
    run_server(port)

