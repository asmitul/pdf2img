#!/bin/bash

# Container settings
IMAGE_NAME="pdf-to-image-web"
CONTAINER_NAME="pdf2img-app"
PORT=8090

# Function to show usage
show_usage() {
    echo "PDF to Image Web Application - Local Runner"
    echo "Usage: $0 [command]"
    echo "Commands:"
    echo "  start    Start the application"
    echo "  stop     Stop the application"
    echo "  restart  Restart the application"
    echo "  status   Show application status"
    exit 1
}

# Check command
if [ $# -lt 1 ]; then
    show_usage
fi

case "$1" in
    start)
        # Check if container exists
        if docker ps -a | grep -q $CONTAINER_NAME; then
            echo "Container already exists. Use 'restart' to rebuild."
            docker start $CONTAINER_NAME
        else
            echo "Building Docker image..."
            docker build -t $IMAGE_NAME .
            
            echo "Creating directories..."
            mkdir -p uploads output
            chmod -R 777 uploads output
            
            echo "Starting container with 50% CPU limit..."
            docker run -d \
              --name $CONTAINER_NAME \
              --cpus=0.5 \
              -p $PORT:8090 \
              -v "$(pwd)/uploads:/app/uploads" \
              -v "$(pwd)/output:/app/output" \
              --restart unless-stopped \
              $IMAGE_NAME
        fi
        
        echo "Application is running at http://localhost:$PORT"
        ;;
        
    stop)
        echo "Stopping container..."
        docker stop $CONTAINER_NAME
        ;;
        
    restart)
        echo "Stopping existing container..."
        docker stop $CONTAINER_NAME || true
        docker rm $CONTAINER_NAME || true
        
        echo "Building Docker image..."
        docker build -t $IMAGE_NAME .
        
        echo "Creating directories..."
        mkdir -p uploads output
        chmod -R 777 uploads output
        
        echo "Starting container with 50% CPU limit..."
        docker run -d \
          --name $CONTAINER_NAME \
          --cpus=0.5 \
          -p $PORT:8090 \
          -v "$(pwd)/uploads:/app/uploads" \
          -v "$(pwd)/output:/app/output" \
          --restart unless-stopped \
          $IMAGE_NAME
          
        echo "Application is running at http://localhost:$PORT"
        ;;
        
    status)
        if docker ps | grep -q $CONTAINER_NAME; then
            echo "Application is running at http://localhost:$PORT"
            docker ps | grep $CONTAINER_NAME
        else
            echo "Application is not running"
        fi
        ;;
        
    *)
        show_usage
        ;;
esac

# # Run the script with the appropriate command
# chmod +x local-run.sh

# # Start the application
# ./local-run.sh start

# # Check status
# ./local-run.sh status

# # Restart (rebuild and restart)
# ./local-run.sh restart

# # Stop the application
# ./local-run.sh stop