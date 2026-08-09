#!/bin/bash
# Server control via direct Java PID
case "$1" in
    stop)
        pkill -f "java.*neoforge"
        echo "Server stopped"
        ;;
    start)
        cd /home/host/neorunner
        export JAVA_HOME=/usr/lib/jvm/java-25-openjdk-amd64
        nohup ./run.sh > /dev/null 2>&1 &
        echo "Server started"
        ;;
    restart)
        pkill -f "java.*neoforge"
        sleep 3
        cd /home/host/neorunner
        export JAVA_HOME=/usr/lib/jvm/java-25-openjdk-amd64
        nohup ./run.sh > /dev/null 2>&1 &
        echo "Server restarted"
        ;;
    status)
        if pgrep -f "java.*neoforge" > /dev/null; then
            echo '{"running":true}'
        else
            echo '{"running":false}'
        fi
        ;;
esac