#!/bin/bash
export JAVA_HOME=/opt/tools/jdk8
export PATH="$JAVA_HOME/bin:$PATH"
/opt/tools/maven/bin/mvn -version 2>&1 | head -2
echo "---"
echo "class T{public static void main(String[] a){System.out.println(42);}}" > /tmp/T.java
$JAVA_HOME/bin/javac /tmp/T.java && $JAVA_HOME/bin/java -cp /tmp T && echo "JDK8 compile+run OK"
echo "---"
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
/opt/tools/maven/bin/mvn -version 2>&1 | head -1
