#!/bin/bash
# author: liu he

# need args: VM-name

DEFAULT_IMAGE_PATH=/var/lib/libvirt/template/
DEFAULT_VM_PATH=/var/lib/libvirt/images/

if [ ! -d "$DEFAULT_IMAGE_PATH" ]; then
    mkdir -p $DEFAULT_IMAGE_PATH
fi

# check is exist the vm or not, and the vm is running or not
line1=`virsh list --all | awk '{ print $2 }' | grep -w $1 | wc -l`

if [ $line1 -eq 1 ] 
then
    echo 'log info: vm exist...\n' >&1
else
    echo 'log error: vm not exist...\n' >&2
    exit 1
fi

# check is exist the image or not
if [ ! -f ${DEFAULT_IMAGE_PATH}${1}'.xml' ]
then
  echo "log info: image not exist, begin create image...\n" >&1
else
  echo "log error: image has exist, exit...\n" >&2
  exit 1
fi


# check DEAFULT_PATH disk space support to create image or not
DISK_FILE_PATH=`virsh domblklist $1 | awk 'NR==3 {print $2 }'`
if [ ! -n "$DISK_FILE_PATH" ]; then
  echo "log error: can't find vm disk file..." >&2
  exit 1
fi

NEED_SPACE=`du -m $DISK_FILE_PATH | awk '{print $1}'`
DISK_SPACE=`df -m $DEFAULT_IMAGE_PATH | awk '{ print $4 }' | tail -n +2 |awk '{sum+=$1} END {print sum}'`
if [ $DISK_SPACE -gt $NEED_SPACE ]
then
    echo $NEED_SPACE
    echo $DISK_SPACE
    echo "log info: space is enough..." >&1
else
    echo $NEED_SPACE
    echo $DISK_SPACE
    echo "log error: space is not enough..." >&2
    exit 1
fi


# check the vm status shut down or not
line2=`virsh list --all | grep -w $1  | grep 'shut' | wc -l`

if [ $line2 -eq 1 ]
then
    echo 'log info: vm has shut down...' >&1
else
    echo 'log error: vm is running..., please shut down firstly...\n' >&2
    exit 1
#    virsh destroy $1
#    if [ $? -ne 0 ]; then
#        echo "occur error while shutting down vm..."
#        exit 1
#    else
#        echo "shut down vm successfully..."
#    fi
fi

# step 1 dump  vm xml
virsh dumpxml $1 > ${DEFAULT_IMAGE_PATH}${1}.xml

if [ $? -ne 0 ]; then
    echo "log error: dump xml file fail...\n" >&2
    exit 1
else
    echo "log info: dump xml file successfully...\n" >&1
fi

# step 2 copy the file to default path, and change the file path in xml

#IMAGEPATH=`cat ${DEFAULT_PATH}${1}.xml | grep 'source file' | grep 'qcow2'| cut -d "'" -f 2`

IMAGE_PATH=`virsh domblklist $1 | awk 'NR==3 {print $2 }'`
echo $IMAGE_PATH
cp ${IMAGE_PATH} ${DEFAULT_IMAGE_PATH}${1}'.'${IMAGE_PATH#*.}

if [ $? -ne 0 ]; then
    echo "log error: copy image file fail...\n" >&2
    # operation fial, roll back
    rm ${DEFAULT_IMAGE_PATH}${1}.xml
    exit 1
else
    sed -i 's#'${IMAGE_PATH}'#'${DEFAULT_IMAGE_PATH}${1}'.'${IMAGE_PATH#*.}'#g' ${DEFAULT_IMAGE_PATH}${1}.xml
    if [ $? -ne 0 ]; then
        echo "log error: change the image file path in xml file failed\n" >&2
        # operation fial, roll back
        rm -f ${DEFAULT_IMAGE_PATH}${1}.xml ${DEFAULT_IMAGE_PATH}${1}'.'${IMAGE_PATH#*.}
        exit 1
    else
        echo "log info: change the image file path in xml file successfully...\n" >&1
    fi
    echo "log info: copy image file successfully...\n" >&1

    # init image
#    virt-sysprep -a ${DEFAULT_IMAGE_PATH}${IMAGE_PATH##*/}
#    if [ $? -ne 0 ]; then
#        echo "log error: init image failed\n"
#        # operation fial, roll back
#        rm -f ${DEFAULT_IMAGE_PATH}${1}.xml ${DEFAULT_IMAGE_PATH}${IMAGE_PATH##*/}
#        exit 1
#    else
#        echo "log info: init image successfully...\n"
#    fi
    # record old disk file path
#    FILE_NAME=`echo ${IMAGE_PATH##*/} | cut -d '.' -f 1`
    echo ""${IMAGE_PATH} > ${DEFAULT_IMAGE_PATH}${1}'.path'
fi

# step 3 undefine the vm
#virsh undefine --remove-all-storage --delete-snapshots $1 2>&1
virsh undefine --remove-all-storage --delete-snapshots $1 >/dev/null 2>&1
if [ $? -ne 0 ]; then
    # undefine error, check the vm exist or not
    VM_IS_EXIST=`virsh list --all | awk '{ print $2 }' | grep -w ${IMAGE_PATH##*/} | wc -l`
    if [ $VM_IS_EXIST -eq 1 ]
    then
        # undefine fail, delete the files
        echo "log error: undefine fail, delete the files...\n" >&2
        rm -f ${DEFAULT_IMAGE_PATH}${1}.xml ${DEFAULT_IMAGE_PATH}${1}'.'${IMAGE_PATH#*.} ${DEFAULT_IMAGE_PATH}${1}'.path'
        exit 1
    else
        echo 'log info: undefine vm successfully, delete the disk file manually...\n' >&1
        rm -f ${IMAGE_PATH}
#        if [ ! -d "${IMAGE_PATH}" ]; then
#            echo 'log info: delete the disk file successfully...\n'
#        else
#            rm -f ${IMAGE_PATH}
#            echo 'log info: delete the disk file manually successful...\n'
#        fi
        exit 0
    fi
else
    echo "log info: undifine vm successfully...\n" >&1
fi
