#!/bin/bash

set -e

# Variables
TRUST_ANCHOR_NAME="MyTrustAnchor"
PROFILE_NAME="MyProfile"
ROLE_NAME="RolesAnywhereAssumableRole"
POLICY_NAME="RolesAnywherePolicy"
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
CREDENTIALS_FILE="./aws_credentials.conf"

# Function to check if a trust anchor exists
function get_trust_anchor_arn {
    aws rolesanywhere list-trust-anchors \
        --region $REGION \
        --query "trustAnchors[?name=='$TRUST_ANCHOR_NAME'].trustAnchorArn" \
        --output text
}

# Function to check if a profile exists
function get_profile_arn {
    aws rolesanywhere list-profiles \
        --region $REGION \
        --query "profiles[?name=='$PROFILE_NAME'].profileArn" \
        --output text
}

# Function to check if an IAM role exists
function get_role_arn {
    aws iam get-role \
        --role-name "$ROLE_NAME" \
        --query 'Role.Arn' \
        --output text 2>/dev/null || true
}

# Step 1: Generate CA private key and certificate
if [[ -f "ca.key" && -f "ca.crt" ]]; then
    echo "CA private key and certificate already exist. Skipping generation."
else
    echo "Generating CA private key and certificate with proper basic constraints..."

    openssl genrsa -out ca.key 4096

    cat > ca.conf <<EOF
[ req ]
default_bits           = 4096
default_md             = sha256
distinguished_name     = req_distinguished_name
x509_extensions        = v3_ca

[ req_distinguished_name ]
countryName            = US
commonName             = MyRootCA

[ v3_ca ]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical,CA:TRUE
keyUsage               = critical, digitalSignature, cRLSign, keyCertSign
EOF

    openssl req -new -x509 -days 3650 -key ca.key -out ca.crt -config ca.conf -subj "/CN=MyRootCA" -extensions v3_ca
fi

# Step 2: Create a trust anchor with the CA certificate
TRUST_ANCHOR_ARN=$(get_trust_anchor_arn)
if [[ -n "$TRUST_ANCHOR_ARN" ]]; then
    echo "Trust Anchor '$TRUST_ANCHOR_NAME' already exists with ARN: $TRUST_ANCHOR_ARN"
else
    echo "Creating a trust anchor in IAM Roles Anywhere..."
    CA_CERT_BASE64=$(base64 -w 0 ca.crt)
    TRUST_ANCHOR_ARN=$(aws rolesanywhere create-trust-anchor \
        --name "$TRUST_ANCHOR_NAME" \
        --source "sourceData={x509CertificateData=$CA_CERT_BASE64},sourceType=CERTIFICATE_BUNDLE" \
        --region $REGION \
        --query 'trustAnchor.trustAnchorArn' \
        --enabled \
        --output text)
    echo "Created Trust Anchor with ARN: $TRUST_ANCHOR_ARN"
fi

# Step 3: Create an IAM role with trust policy for Roles Anywhere
ROLE_ARN=$(get_role_arn)
if [[ -n "$ROLE_ARN" ]]; then
    echo "IAM Role '$ROLE_NAME' already exists with ARN: $ROLE_ARN"
else
    echo "Creating IAM role for Roles Anywhere..."
    ROLE_ARN=$(aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document file://<(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "rolesanywhere.amazonaws.com"
            },
            "Action": [
                "sts:AssumeRole",
                "sts:TagSession",
                "sts:SetSourceIdentity"
            ],
            "Condition": {
                "ArnEquals": {
                    "aws:SourceArn": "$TRUST_ANCHOR_ARN"
                }
            }
        }
    ]
}
EOF
    ) \
        --description "Role assumable by IAM Roles Anywhere via trust anchor" \
        --query 'Role.Arn' \
        --output text)
    echo "Created IAM Role with ARN: $ROLE_ARN"

    # Attach a policy to the role 
    echo "Attaching policy to the role..."
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "$POLICY_NAME" \
        --policy-document file://<(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "sts:GetCallerIdentity",
            "Resource": "*"
        }
    ]
}
EOF
    )
fi

# Step 4: Create a profile in IAM Roles Anywhere
PROFILE_ARN=$(get_profile_arn)
if [[ -n "$PROFILE_ARN" ]]; then
    echo "Profile '$PROFILE_NAME' already exists with ARN: $PROFILE_ARN"
else
    echo "Creating a profile in IAM Roles Anywhere..."
    PROFILE_ARN=$(aws rolesanywhere create-profile \
        --name "$PROFILE_NAME" \
        --role-arns "$ROLE_ARN" \
        --duration-seconds 3600 \
        --enabled \
        --region $REGION \
        --query 'profile.profileArn' \
        --output text)
    echo "Created Profile with ARN: $PROFILE_ARN"
fi

# Step 5: Generate client certificate signed by the CA
if [[ -f "client.key" && -f "client.crt" ]]; then
    echo "Client certificate and key already exist. Skipping generation."
else
    echo "Generating client certificate signed by the CA..."
    openssl genrsa -out client.key 4096

    cat > client.conf <<EOF
[ req ]
default_bits           = 2048
default_md             = sha256
distinguished_name     = req_distinguished_name
req_extensions         = v3_req

[ req_distinguished_name ]
countryName            = US
commonName             = sample-user

[ v3_req ]
keyUsage               = digitalSignature
extendedKeyUsage       = clientAuth
basicConstraints       = critical,CA:FALSE
EOF

    openssl req -new -key client.key -out client.csr -config client.conf -subj "/CN=sample-user"

    openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 3650 -extensions v3_req -extfile client.conf
fi

# Check if aws_signing_helper is available
if ! command -v ./aws_signing_helper &> /dev/null
then
    echo "aws_signing_helper not found. Please ensure AWS CLI v2 is installed."
    exit 1
fi

# Create AWS CLI credentials file with credential_process
cat > $CREDENTIALS_FILE <<EOF
[default]
credential_process = ./aws_signing_helper credential-process \
--certificate client.crt \
--private-key client.key \
--trust-anchor-arn $TRUST_ANCHOR_ARN \
--profile-arn $PROFILE_ARN \
--role-arn $ROLE_ARN \
--region $REGION
EOF

echo "----"
echo "You can now assume $ROLE_ARN, just execute this:"
echo ""
echo "export AWS_SHARED_CREDENTIALS_FILE=$CREDENTIALS_FILE"
echo "aws sts get-caller-identity --region $REGION"
