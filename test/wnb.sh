#!/bin/bash
for i in {62612..62619}
do
curl -sI --max-time 0.6 http://localhost:$i/walletnotify?$1
done

