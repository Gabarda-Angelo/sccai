<?php
include_once 'connectdb.php';
session_start();
include_once "header.php";
?>

<!-- Content Wrapper. Contains page content -->
<div class="content-wrapper">
    <!-- Content Header (Page header) -->
    <div class="content-header">
        <div class="container-fluid">
            <div class="row mb-2">
                <div class="col-sm-6">
                    <h1 class="m-0">Ask anything about your store</h1>
                </div>
                <div class="col-sm-6">
                    <ol class="breadcrumb float-sm-right">
                        <!-- Breadcrumb items if needed -->
                    </ol>
                </div>
            </div>
        </div>
    </div>
    <!-- /.content-header -->

    <!-- Main content -->
    <div class="content">
        <div class="container-fluid">
            <div class="row">
                <div class="col-lg-12">
                    <div class="card card-secondary card-outline">
                        <div class="card-header">
                            <h5 class="m-0">AI</h5>
                        </div>
                        <div class="card-body">
                            <!-- Embed the Streamlit app via an iframe -->
                            <iframe src="http://localhost:8501" style="width: 100%; height: 600px; border: none;"></iframe>
                        </div>
                    </div>
                </div>
                <!-- /.col-lg-12 -->
            </div>
        </div>
    </div>
    <!-- /.content -->
</div>
<!-- /.content-wrapper -->

<?php
include_once "footer.php";
?>
