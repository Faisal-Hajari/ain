# A static page and a proxy. There is no application code here at all, which
# is the point: the editor was being served by the analytics API, which meant
# the service that answers KPI queries also had a route for an HTML file and
# an environment variable naming where it sat on disk.
FROM nginx:1.27-alpine

COPY applications/geometry-editor/nginx.conf /etc/nginx/conf.d/default.conf
COPY applications/geometry-editor/editor.html /usr/share/nginx/html/editor.html

EXPOSE 8101
