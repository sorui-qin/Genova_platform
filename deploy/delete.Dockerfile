FROM genova/delete:1.0.1
COPY delete-runtime-patch.py /tmp/delete-runtime-patch.py
RUN python3 /tmp/delete-runtime-patch.py && rm /tmp/delete-runtime-patch.py
RUN rm -rf /platform/genova_runtime
COPY genova_runtime /platform/genova_runtime
