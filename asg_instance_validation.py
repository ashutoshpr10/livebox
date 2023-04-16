import boto3
import os
import sys
import datetime
from dateutil.tz import tzutc

aws_access_key_id=os.environ['aws_access_key_id']
aws_secret_access_key=os.environ['aws_secret_access_key']

def validate_credentials():
    sts_client = boto3.client('sts',aws_access_key_id=aws_access_key_id,aws_secret_access_key=aws_secret_access_key,region_name='ap-south-1')
    try:
        sts_client.get_caller_identity()
    except:
        print("Invalid Credentials")
        sys.exit(0)

def get_ec2_instance_describe(instance_id):
    ec2_client = boto3.client('ec2',aws_access_key_id=aws_access_key_id,aws_secret_access_key=aws_secret_access_key,region_name='ap-south-1')
    ec2_response = ec2_client.describe_instances(InstanceIds = [instance_id])
    return ec2_response
    
def get_asg_describe(asg_name):
    asg_client = boto3.client('autoscaling',aws_access_key_id=aws_access_key_id,aws_secret_access_key=aws_secret_access_key,region_name='ap-south-1')
    asg_response = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    return asg_response

def get_running_instances(asg_response):
    instances = asg_response['AutoScalingGroups'][0]['Instances']
    running_instances = [ instance for instance in instances if instance['LifecycleState'] == 'InService']
    return running_instances

def get_terminated_instances(asg_response):
    instances = asg_response['AutoScalingGroups'][0]['Instances']
    terminated_instances = [ instance for instance in instances if instance['LifecycleState'] != 'InService']
    return terminated_instances

def validate_desired_and_running_instance_count(asg_response):
    desired_count = asg_response['AutoScalingGroups'][0]['DesiredCapacity']
    running_instances = get_running_instances(asg_response)
    return len(running_instances) == desired_count
    
def get_instance_meta_data(instance_id):
    '''
    To get vpc_id, security group and image id
    '''
    instance_response =  get_ec2_instance_describe(instance_id)
    vpc_id = instance_response['Reservations'][0]['Instances'][0]['VpcId']
    sg = instance_response['Reservations'][0]['Instances'][0]['SecurityGroups']
    image_id = instance_response['Reservations'][0]['Instances'][0]['ImageId']
    
    return vpc_id, sg, image_id

def validate_az_distribution(asg_response):
    available_az_set_count = len(asg_response['AutoScalingGroups'][0]['AvailabilityZones'])
    running_instance_count = len(get_running_instances(asg_response))
    assigned_az_set_count = len(set([ instance['AvailabilityZone'] for instance in get_running_instances(asg_response)]))
    if running_instance_count > 1 and running_instance_count <= available_az_set_count and assigned_az_set_count != running_instance_count:
        return False
    elif  running_instance_count > 1 and running_instance_count > available_az_set_count and available_az_set_count != assigned_az_set_count:
        return False
    return True  

def validate_vpcid_sg_imageid_in_asg (asg_response):
    running_instance_id_list = [ instance['InstanceId'] for instance in get_running_instances(asg_response) ]
    first_vpc_id, first_sg, first_image_id =  get_instance_meta_data(instance_id=running_instance_id_list[0])
    
    for instance_id in running_instance_id_list:
        vpc_id, sg, image_id = get_instance_meta_data(instance_id=instance_id)
        if vpc_id != first_vpc_id or sg != first_sg or image_id != first_image_id:
            return False  
    return True

def get_lauchime_for_instance(instance_id):
    instance_response =  get_ec2_instance_describe(instance_id)
    launch_time = instance_response['Reservations'][0]['Instances'][0]['LaunchTime']
    return launch_time
    
def get_longest_running_instance_uptime(asg_response):
    running_instance_id_list = [ instance['InstanceId'] for instance in get_running_instances(asg_response) ]
    logest_instance_uptime =  datetime.datetime.utcnow().replace(tzinfo=tzutc()) - get_lauchime_for_instance(instance_id = running_instance_id_list[0])
    for instance in running_instance_id_list:   
        uptime = datetime.datetime.utcnow().replace(tzinfo=tzutc()) - get_lauchime_for_instance(instance_id = instance)
        if uptime > logest_instance_uptime:
            logest_instance_uptime = uptime
    print("Testcase A passed. Longest running instance uptime: {}.".format(logest_instance_uptime))
    
def next_scheduled_action(asg_name):
    asg_client = boto3.client('autoscaling',aws_access_key_id=aws_access_key_id,aws_secret_access_key=aws_secret_access_key,region_name='ap-south-1')
    scheduled_actions = asg_client.describe_scheduled_actions(AutoScalingGroupName=asg_name)

    now = datetime.datetime.fromisoformat(str(datetime.datetime.utcnow().replace(tzinfo=tzutc())))
    next_action_time = None

    for actions in scheduled_actions['ScheduledUpdateGroupActions']:
        action_time = datetime.datetime.fromisoformat(str(actions['StartTime']))
        if next_action_time is None or abs(now - action_time) < abs(now - next_action_time):
            next_action_time = action_time
            
    if next_action_time is None:
        print("No Scheduled actions are present")
    else:
        # print next scheduled actions time diff from now
        delta_time = datetime.datetime.fromisoformat(str(next_action_time)) - datetime.datetime.fromisoformat(str(now))
        delta_seconds = int(delta_time.total_seconds())
        hh = int(delta_seconds//3600)
        mm = int((delta_seconds % 3600)//60)
        ss = int((delta_seconds % 60))
        print(f"Next Scheduled Action will run in : {hh:02d}:{mm:02d}:{ss:02d}")
    
def launched_and_terminated_today_instance_count(asg_response):
    now = datetime.datetime.utcnow().replace(tzinfo=tzutc())
    terminated_instance_id_list =[ instance['InstanceId'] for instance in get_terminated_instances(asg_response)]
    launch_terminated_same_day_count = 0
    for instance_id in terminated_instance_id_list:
        launch_date = get_lauchime_for_instance(instance_id)['Reservations'][0]['Instances'][0]['LaunchTime'].date()
        if launch_date == now.date():
            launch_terminated_same_day_count+=1
    print(f"Number of instances launcha and terminated today : {launch_terminated_same_day_count}")

def test_case_a(asg_name):
    asg_response =  get_asg_describe(asg_name)

    # if desired capacity is 0
    if asg_response['AutoScalingGroups'][0]['DesiredCapacity'] == 0:
        print("Test Case A passed, ASG has a desired capacity of 0.")
    
    # 1- ASG desired running count should be same as running instances. if mismatch fails
    if not validate_desired_and_running_instance_count(asg_response):
        print("Test Case A failed : Desired running count is not matching with running instance count.")
        sys.exit(0)
    # 2- if more than 1 instance running on ASG, then ec2 instance should on available and distributed on multiple availibity zone.
    if not validate_az_distribution(asg_response):
        print("Test Case A failed : instance are not distributed among avialable az set.")
        sys.exit(0)
    #3- SecuirtyGroup, ImageID and VPCID should be same on ASG running instances. Do not just print.
    if not validate_vpcid_sg_imageid_in_asg(asg_response):
        print("Test Case A failed : SecuirtyGroup, ImageID and VPCID  are not same for ASG running instances.")
        sys.exit(0)
    #4- Findout uptime of ASG running instances and get the longest running instance.
    get_longest_running_instance_uptime(asg_response)

def test_case_b(asg_name):
    asg_response = get_asg_describe(asg_name)
    
    # Find the Scheduled actions of as which is going to run next and calcalate elapsed in hh:mm:ss from current time.
    next_scheduled_action(asg_name)
    
    #Calculate total number instances lunched and terminated on current day.
    launched_and_terminated_today_instance_count(asg_response)

def main(argv):
    print(sys.argv)
    if len(sys.argv)>1:
        asg_name=str(sys.argv[1])
        # validate credentials
        validate_credentials()

        # check asg name is correct
        if len(get_asg_describe(asg_name)['AutoScalingGroups']) == 0 :
            print("Error : ASG name not found. Plase provide correct ASG name")
            sys.exit(0)
        # test case A
        test_case_a('lv-test-cpu')

        # test case B
        test_case_b(asg_name)
        
    else:
        print("Please pass correct arguments")
        print("Usage ./sample-test.py asgname")

if __name__ == "__main__":
    main(sys.argv)
